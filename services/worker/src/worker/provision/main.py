import asyncio
import contextlib
import logging
from typing import Any

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models.control_plane import AS2Partner as GlobalAS2Partner
from database.models.control_plane import AS2Partnership as GlobalAS2Partnership
from database.models.control_plane import InboundRoute as GlobalInboundRoute
from database.models.control_plane import OutboundRoute as GlobalOutboundRoute
from database.models.control_plane import Outbox as GlobalOutbox
from database.models.control_plane import SFTPPartner as GlobalSFTPPartner
from database.models.control_plane import Webhook as GlobalWebhook
from database.models.data_plane import AS2Partner as TenantAS2Partner
from database.models.data_plane import AS2Partnership as TenantAS2Partnership
from database.models.data_plane import InboundRoute as TenantInboundRoute
from database.models.data_plane import OutboundRoute as TenantOutboundRoute
from database.models.data_plane import SFTPPartner as TenantSFTPPartner
from database.models.data_plane import Webhook as TenantWebhook
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from worker.utils import TenantResolver

logger = logging.getLogger(__name__)


async def sync_deletes(
    tenant_id: int, global_session: Any, tenant_session: Any, global_model: Any, tenant_model: Any
) -> None:
    from sqlalchemy import delete, select

    # Get all valid IDs from global
    global_stmt = select(global_model.id).where(global_model.tenant_id == tenant_id)
    # Special handling for AS2Partner which has global partners (tenant_id IS NULL)
    if global_model.__name__ == "AS2Partner":
        global_stmt = select(global_model.id).where(
            (global_model.tenant_id == tenant_id) | (global_model.tenant_id.is_(None))
        )
    global_ids_result = await global_session.execute(global_stmt)
    global_ids = set(global_ids_result.scalars().all())

    # Get all IDs in tenant db
    tenant_stmt = select(tenant_model.id).where(tenant_model.tenant_id == tenant_id)
    tenant_ids_result = await tenant_session.execute(tenant_stmt)
    tenant_ids = set(tenant_ids_result.scalars().all())

    # Delete ids in tenant that are not in global
    ids_to_delete = tenant_ids - global_ids
    if ids_to_delete:
        delete_stmt = delete(tenant_model).where(tenant_model.id.in_(list(ids_to_delete)))
        await tenant_session.execute(delete_stmt)


async def replicate_tenant_config(
    tenant_id: int, global_session: AsyncSession, tenant_session: AsyncSession
) -> None:
    """Replicates configuration from Global DB to Tenant DB Shard."""

    # Replicate AS2Partners
    # We replicate all AS2Partners that belong to this tenant, plus any global ones (tenant_id IS NULL)
    stmt = select(GlobalAS2Partner).where(
        (GlobalAS2Partner.tenant_id == tenant_id) | (GlobalAS2Partner.tenant_id == 0)
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
                prev_public_cert_pem=global_tp.prev_public_cert_pem,
                prev_public_cert_vault_ref=global_tp.prev_public_cert_vault_ref,
                prev_private_key_vault_ref=global_tp.prev_private_key_vault_ref,
                url=global_tp.url,
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
                    "prev_public_cert_pem": global_tp.prev_public_cert_pem,
                    "prev_public_cert_vault_ref": global_tp.prev_public_cert_vault_ref,
                    "prev_private_key_vault_ref": global_tp.prev_private_key_vault_ref,
                    "url": global_tp.url,
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
                name=global_ps.name,
                local_partner_id=global_ps.local_partner_id,
                remote_partner_id=global_ps.remote_partner_id,
                credentials_vault_ref=global_ps.credentials_vault_ref,
                mdn_type=global_ps.mdn_type,
                mdn_url=global_ps.mdn_url,
                encryption_algorithm=global_ps.encryption_algorithm,
                signature_algorithm=global_ps.signature_algorithm,
                advanced_flags=global_ps.advanced_flags,
                active=global_ps.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": global_ps.name,
                    "local_partner_id": global_ps.local_partner_id,
                    "remote_partner_id": global_ps.remote_partner_id,
                    "credentials_vault_ref": global_ps.credentials_vault_ref,
                    "mdn_type": global_ps.mdn_type,
                    "mdn_url": global_ps.mdn_url,
                    "encryption_algorithm": global_ps.encryption_algorithm,
                    "signature_algorithm": global_ps.signature_algorithm,
                    "advanced_flags": global_ps.advanced_flags,
                    "active": global_ps.active,
                },
            )
        )
        await tenant_session.execute(insert_ps_stmt)

    # Replicate SFTPPartners
    sftp_stmt = select(GlobalSFTPPartner).where(GlobalSFTPPartner.tenant_id == tenant_id)
    sftp_result = await global_session.execute(sftp_stmt)
    for global_sftp in sftp_result.scalars():
        insert_sftp_stmt = (
            insert(TenantSFTPPartner)
            .values(
                id=global_sftp.id,
                tenant_id=tenant_id,
                name=global_sftp.name,
                host=global_sftp.host,
                port=global_sftp.port,
                username=global_sftp.username,
                inbound_remote_path=global_sftp.inbound_remote_path,
                outbound_remote_path=global_sftp.outbound_remote_path,
                host_key=global_sftp.host_key,
                password_encrypted=global_sftp.password_encrypted,
                credentials_vault_ref=global_sftp.credentials_vault_ref,
                active=global_sftp.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": global_sftp.name,
                    "host": global_sftp.host,
                    "port": global_sftp.port,
                    "username": global_sftp.username,
                    "inbound_remote_path": global_sftp.inbound_remote_path,
                    "outbound_remote_path": global_sftp.outbound_remote_path,
                    "host_key": global_sftp.host_key,
                    "password_encrypted": global_sftp.password_encrypted,
                    "credentials_vault_ref": global_sftp.credentials_vault_ref,
                    "active": global_sftp.active,
                },
            )
        )
        await tenant_session.execute(insert_sftp_stmt)

    # Replicate Webhooks
    wh_stmt = select(GlobalWebhook).where(GlobalWebhook.tenant_id == tenant_id)
    wh_result = await global_session.execute(wh_stmt)
    for global_wh in wh_result.scalars():
        insert_wh_stmt = (
            insert(TenantWebhook)
            .values(
                id=global_wh.id,
                tenant_id=tenant_id,
                name=global_wh.name,
                url=global_wh.url,
                auth_header_vault_ref=global_wh.auth_header_vault_ref,
                active=global_wh.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": global_wh.name,
                    "url": global_wh.url,
                    "auth_header_vault_ref": global_wh.auth_header_vault_ref,
                    "active": global_wh.active,
                },
            )
        )
        await tenant_session.execute(insert_wh_stmt)

    # Replicate InboundRoutes
    ir_stmt = select(GlobalInboundRoute).where(GlobalInboundRoute.tenant_id == tenant_id)
    ir_result = await global_session.execute(ir_stmt)
    for global_ir in ir_result.scalars():
        insert_ir_stmt = (
            insert(TenantInboundRoute)
            .values(
                id=global_ir.id,
                tenant_id=tenant_id,
                name=global_ir.name,
                isa_sender_id=global_ir.isa_sender_id,
                isa_receiver_id=global_ir.isa_receiver_id,
                transaction_type=global_ir.transaction_type,
                processing_mode=global_ir.processing_mode,
                webhook_id=global_ir.webhook_id,
                as2_partner_id=global_ir.as2_partner_id,
                sftp_partner_id=global_ir.sftp_partner_id,
                active=global_ir.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": global_ir.name,
                    "isa_sender_id": global_ir.isa_sender_id,
                    "isa_receiver_id": global_ir.isa_receiver_id,
                    "transaction_type": global_ir.transaction_type,
                    "processing_mode": global_ir.processing_mode,
                    "webhook_id": global_ir.webhook_id,
                    "as2_partner_id": global_ir.as2_partner_id,
                    "sftp_partner_id": global_ir.sftp_partner_id,
                    "active": global_ir.active,
                },
            )
        )
        await tenant_session.execute(insert_ir_stmt)

    # Replicate OutboundRoutes
    or_stmt = select(GlobalOutboundRoute).where(GlobalOutboundRoute.tenant_id == tenant_id)
    or_result = await global_session.execute(or_stmt)
    for global_or in or_result.scalars():
        insert_or_stmt = (
            insert(TenantOutboundRoute)
            .values(
                id=global_or.id,
                tenant_id=tenant_id,
                name=global_or.name,
                isa_sender_id=global_or.isa_sender_id,
                isa_receiver_id=global_or.isa_receiver_id,
                transaction_type=global_or.transaction_type,
                processing_mode=global_or.processing_mode,
                as2_partner_id=global_or.as2_partner_id,
                sftp_partner_id=global_or.sftp_partner_id,
                active=global_or.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": global_or.name,
                    "isa_sender_id": global_or.isa_sender_id,
                    "isa_receiver_id": global_or.isa_receiver_id,
                    "transaction_type": global_or.transaction_type,
                    "processing_mode": global_or.processing_mode,
                    "as2_partner_id": global_or.as2_partner_id,
                    "sftp_partner_id": global_or.sftp_partner_id,
                    "active": global_or.active,
                },
            )
        )
        await tenant_session.execute(insert_or_stmt)

    # Sync deletes for all configurations (Dependent children first)
    await sync_deletes(
        tenant_id, global_session, tenant_session, GlobalOutboundRoute, TenantOutboundRoute
    )
    await sync_deletes(
        tenant_id, global_session, tenant_session, GlobalInboundRoute, TenantInboundRoute
    )
    await sync_deletes(tenant_id, global_session, tenant_session, GlobalWebhook, TenantWebhook)
    await sync_deletes(
        tenant_id, global_session, tenant_session, GlobalSFTPPartner, TenantSFTPPartner
    )
    await sync_deletes(
        tenant_id, global_session, tenant_session, GlobalAS2Partnership, TenantAS2Partnership
    )
    await sync_deletes(
        tenant_id, global_session, tenant_session, GlobalAS2Partner, TenantAS2Partner
    )

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
                    GlobalOutbox.event_type.in_(
                        [
                            "AS2_PARTNER_CREATED",
                            "AS2_PARTNERSHIP_CREATED",
                            "AS2_PARTNER_UPDATED",
                            "AS2_PARTNERSHIP_UPDATED",
                            "AS2_PARTNER_DELETED",
                            "AS2_PARTNERSHIP_DELETED",
                            "SFTP_PARTNER_CREATED",
                            "SFTP_PARTNER_UPDATED",
                            "SFTP_PARTNER_DELETED",
                            "WEBHOOK_CREATED",
                            "WEBHOOK_UPDATED",
                            "WEBHOOK_DELETED",
                            "INBOUND_ROUTE_CREATED",
                            "INBOUND_ROUTE_UPDATED",
                            "INBOUND_ROUTE_DELETED",
                            "OUTBOUND_ROUTE_CREATED",
                            "OUTBOUND_ROUTE_UPDATED",
                            "OUTBOUND_ROUTE_DELETED",
                        ]
                    ),
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
