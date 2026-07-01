import asyncio
import contextlib
import logging

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models.control_plane import AS2Partner as GlobalAS2Partner
from database.models.control_plane import AS2Partnership as GlobalAS2Partnership
from database.models.control_plane import Outbox as GlobalOutbox
from database.models.data_plane import AS2Partner as TenantAS2Partner
from database.models.data_plane import AS2Partnership as TenantAS2Partnership
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from worker.utils import TenantResolver

logger = logging.getLogger(__name__)


async def replicate_tenant_config(
    tenant_id: int, global_session: AsyncSession, tenant_session: AsyncSession
) -> None:
    """Replicates configuration from Global DB to Tenant DB Shard."""

    # Replicate AS2Partners
    # We replicate all AS2Partners that belong to this tenant, plus any global ones (tenant_id IS NULL)
    stmt = select(GlobalAS2Partner).where(
        (GlobalAS2Partner.tenant_id == tenant_id) | (GlobalAS2Partner.tenant_id.is_(None))
    )
    tp_result = await global_session.execute(stmt)

    for global_tp in tp_result.scalars():
        insert_stmt = (
            insert(TenantAS2Partner)
            .values(
                id=global_tp.id,
                tenant_id=tenant_id,  # Use destination tenant_id for replicated partners
                name=global_tp.name,
                as2_id=global_tp.as2_id,
                is_local=global_tp.is_local,
                public_cert_pem=global_tp.public_cert_pem,
                public_cert_vault_ref=global_tp.public_cert_vault_ref,
                private_key_vault_ref=global_tp.private_key_vault_ref,
                active=global_tp.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "tenant_id": tenant_id,
                    "name": global_tp.name,
                    "as2_id": global_tp.as2_id,
                    "is_local": global_tp.is_local,
                    "public_cert_pem": global_tp.public_cert_pem,
                    "public_cert_vault_ref": global_tp.public_cert_vault_ref,
                    "private_key_vault_ref": global_tp.private_key_vault_ref,
                    "active": global_tp.active,
                },
            )
        )
        await tenant_session.execute(insert_stmt)

    # Replicate AS2Partnerships
    ps_stmt = select(GlobalAS2Partnership).where(GlobalAS2Partnership.tenant_id == tenant_id)
    ps_result = await global_session.execute(ps_stmt)

    for global_ps in ps_result.scalars():
        insert_ps_stmt = (
            insert(TenantAS2Partnership)
            .values(
                id=global_ps.id,
                tenant_id=tenant_id,
                local_partner_id=global_ps.local_partner_id,
                remote_partner_id=global_ps.remote_partner_id,
                local_url=global_ps.local_url,
                remote_url=global_ps.remote_url,
                credentials_vault_ref=global_ps.credentials_vault_ref,
                mdn_type=global_ps.mdn_type,
                mdn_url=global_ps.mdn_url,
                encryption_algorithm=global_ps.encryption_algorithm,
                signature_algorithm=global_ps.signature_algorithm,
                advanced_flags=global_ps.advanced_flags,
                edi_version=global_ps.edi_version,
                active=global_ps.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "local_partner_id": global_ps.local_partner_id,
                    "remote_partner_id": global_ps.remote_partner_id,
                    "local_url": global_ps.local_url,
                    "remote_url": global_ps.remote_url,
                    "credentials_vault_ref": global_ps.credentials_vault_ref,
                    "mdn_type": global_ps.mdn_type,
                    "mdn_url": global_ps.mdn_url,
                    "encryption_algorithm": global_ps.encryption_algorithm,
                    "signature_algorithm": global_ps.signature_algorithm,
                    "edi_version": global_ps.edi_version,
                    "advanced_flags": global_ps.advanced_flags,
                    "active": global_ps.active,
                },
            )
        )
        await tenant_session.execute(insert_ps_stmt)

    await tenant_session.commit()
    logger.info(f"Successfully replicated AS2 configuration for tenant_id={tenant_id}")


async def poll_global_outbox(
    db_router: DatabaseRouter,
    resolver: TenantResolver,
) -> None:
    """Polls the Global Outbox for provisioning events."""
    logger.info("Started polling Global Outbox for PROVISION events")

    while True:
        global_gen = db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            # Find a pending provision event
            stmt = (
                select(GlobalOutbox)
                .where(
                    GlobalOutbox.status == "PENDING",
                    GlobalOutbox.event_type.in_(["AS2_PARTNER_CREATED", "AS2_PARTNERSHIP_CREATED"]),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            result = await global_session.execute(stmt)
            outbox_event = result.scalar_one_or_none()

            if outbox_event:
                payload = outbox_event.payload
                tenant_id = payload.get("tenant_id")

                if tenant_id is None:
                    logger.error(f"Missing tenant_id in provision event: {outbox_event.id}")
                    outbox_event.status = "FAILED"
                    await global_session.commit()
                    continue

                logger.info(f"Processing provision event for tenant_id={tenant_id}")

                shard_name, shard_dsn = await resolver.resolve(tenant_id)
                tenant_gen = db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
                tenant_session = await tenant_gen.__anext__()
                try:
                    await replicate_tenant_config(tenant_id, global_session, tenant_session)

                    # Mark outbox event as processed
                    outbox_event.status = "PROCESSED"
                    await global_session.commit()
                except (ValueError, KeyError) as e:
                    # Permanent data errors: bad payload or missing key — mark FAILED
                    await tenant_session.rollback()
                    logger.error(f"Permanent provisioning failure for tenant {tenant_id}: {e}")
                    outbox_event.status = "FAILED"
                    await global_session.commit()
                except Exception as e:
                    # Transient errors (network, DB): leave PENDING for retry
                    await tenant_session.rollback()
                    logger.exception(
                        f"Transient error provisioning tenant {tenant_id}, will retry: {e}"
                    )
                    # Do NOT change status — let the poller pick it up again
                finally:
                    with contextlib.suppress(StopAsyncIteration):
                        await tenant_gen.__anext__()

        except Exception as e:
            logger.exception(f"Error polling global outbox: {e}")
            await asyncio.sleep(5)
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()

        # Sleep before polling again
        await asyncio.sleep(5)


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    await poll_global_outbox(db_router, resolver)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
