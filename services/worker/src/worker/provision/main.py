import asyncio
import contextlib
import logging

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models.control_plane import (
    Connection as GlobalConn,
)
from database.models.control_plane import (
    Outbox as GlobalOutbox,
)
from database.models.control_plane import (
    Route as GlobalRoute,
)
from database.models.control_plane import (
    TradingPartner as GlobalTP,
)
from database.models.data_plane import (
    Connection as TenantConn,
)
from database.models.data_plane import (
    Route as TenantRoute,
)
from database.models.data_plane import (
    TradingPartner as TenantTP,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from worker.utils import TenantResolver

logger = logging.getLogger(__name__)


async def replicate_tenant_config(
    tenant_id: int, global_session: AsyncSession, tenant_session: AsyncSession
) -> None:
    """Replicates configuration from Global DB to Tenant DB Shard."""

    # 1. Replicate TradingPartners
    tp_result = await global_session.execute(
        select(GlobalTP).where(GlobalTP.tenant_id == tenant_id)
    )
    for global_tp in tp_result.scalars():
        stmt = (
            insert(TenantTP)
            .values(
                id=global_tp.id,
                partner_name=global_tp.partner_name,
                as2_id=global_tp.as2_id,
                direction=global_tp.direction,
                active=global_tp.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "partner_name": global_tp.partner_name,
                    "as2_id": global_tp.as2_id,
                    "direction": global_tp.direction,
                    "active": global_tp.active,
                },
            )
        )
        await tenant_session.execute(stmt)

    # 2. Replicate Connections
    conn_result = await global_session.execute(
        select(GlobalConn).where(GlobalConn.tenant_id == tenant_id)
    )
    for global_conn in conn_result.scalars():
        stmt = (
            insert(TenantConn)
            .values(
                id=global_conn.id,
                trading_partner_id=global_conn.trading_partner_id,
                connection_type=global_conn.connection_type,
                host=global_conn.host,
                port=global_conn.port,
                direction=global_conn.direction,
                credentials_vault_ref=global_conn.credentials_vault_ref,
                poll_interval_secs=global_conn.poll_interval_secs,
                active=global_conn.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "connection_type": global_conn.connection_type,
                    "host": global_conn.host,
                    "port": global_conn.port,
                    "direction": global_conn.direction,
                    "credentials_vault_ref": global_conn.credentials_vault_ref,
                    "poll_interval_secs": global_conn.poll_interval_secs,
                    "active": global_conn.active,
                },
            )
        )
        await tenant_session.execute(stmt)

    # 3. Replicate Routes
    route_result = await global_session.execute(
        select(GlobalRoute).where(GlobalRoute.tenant_id == tenant_id)
    )
    for global_route in route_result.scalars():
        stmt = (
            insert(TenantRoute)
            .values(
                id=global_route.id,
                source_partner_id=global_route.source_partner_id,
                target_partner_id=global_route.target_partner_id,
                source_format=global_route.source_format,
                target_format=global_route.target_format,
                transaction_type=global_route.transaction_type,
                active=global_route.active,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "source_partner_id": global_route.source_partner_id,
                    "target_partner_id": global_route.target_partner_id,
                    "source_format": global_route.source_format,
                    "target_format": global_route.target_format,
                    "transaction_type": global_route.transaction_type,
                    "active": global_route.active,
                },
            )
        )
        await tenant_session.execute(stmt)

    await tenant_session.commit()
    logger.info(f"Successfully replicated configuration for tenant_id={tenant_id}")


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
                    GlobalOutbox.event_type == "TRADING_PARTNER_PROVISION",
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            result = await global_session.execute(stmt)
            outbox_event = result.scalar_one_or_none()

            if outbox_event:
                payload = outbox_event.payload
                tenant_id = payload.get("tenant_id")

                if not tenant_id:
                    logger.error(f"Missing tenant_id in provision event: {outbox_event.id}")
                    outbox_event.status = "FAILED"  # type: ignore
                    await global_session.commit()
                    continue

                logger.info(f"Processing provision event for tenant_id={tenant_id}")

                shard_name, shard_dsn = await resolver.resolve(tenant_id)
                tenant_gen = db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
                tenant_session = await tenant_gen.__anext__()
                try:
                    await replicate_tenant_config(tenant_id, global_session, tenant_session)

                    # Mark outbox event as processed
                    outbox_event.status = "PROCESSED"  # type: ignore
                    await global_session.commit()
                except (ValueError, KeyError) as e:
                    # Permanent data errors: bad payload or missing key — mark FAILED
                    await tenant_session.rollback()
                    logger.error(f"Permanent provisioning failure for tenant {tenant_id}: {e}")
                    outbox_event.status = "FAILED"  # type: ignore
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
