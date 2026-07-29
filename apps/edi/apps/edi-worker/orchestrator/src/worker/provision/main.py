import asyncio
import logging

import asyncpg
from config.settings import get_settings
from database.connection import DatabaseRouter
from dotenv import load_dotenv

from worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from worker.adapters.sqs_outbox import SqsOutboxAdapter
from worker.adapters.sqs_publisher import SqsPublisherAdapter
from worker.core.control_plane_outbox_relay import ControlPlaneOutboxRelayService
from worker.core.service import ProvisioningWorkerService

load_dotenv()

logger = logging.getLogger(__name__)

PROVISIONING_QUEUE_NAME = "edi-tenant-sync.fifo"


async def run_worker(service: ProvisioningWorkerService) -> None:
    logger.info("Started polling SQS for PROVISION events")
    while True:
        try:
            processed_event = await service.process_next_event()
            # The SQS receive_message already blocks for up to 5 seconds (WaitTimeSeconds=5)
            # We don't need to sleep here if we didn't process an event, but we can do a tiny yield
            if not processed_event:
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.exception(f"Error in provisioning loop: {e}")
            await asyncio.sleep(5)


async def run_outbox_relay(
    db_router: DatabaseRouter, message_publisher: SqsPublisherAdapter
) -> None:
    """
    Dedicated background daemon for real-time control plane outbox relay.
    Uses PostgreSQL LISTEN/NOTIFY for instant, zero-polling wakeups, backed by a 60s failsafe.
    """
    relay_service = ControlPlaneOutboxRelayService(db_router, message_publisher)
    queue = asyncio.Queue()

    def handle_notify(connection, pid, channel, payload):
        queue.put_nowait(payload)

    settings = get_settings()
    # asyncpg.connect requires a postgresql:// URL, not postgresql+asyncpg://
    dsn = settings.database.global_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = None
    try:
        while True:
            try:
                if not conn or conn.is_closed():
                    conn = await asyncpg.connect(dsn)
                    await conn.add_listener("control_plane_outbox_inserted", handle_notify)
                    logger.info("Connected and listening to 'control_plane_outbox_inserted'")

                    # Catch-up sweep on boot/reconnect to guarantee at-least-once delivery
                    await relay_service.relay_pending_events()

                # Wait for notification or 60s failsafe timeout
                try:
                    await asyncio.wait_for(queue.get(), timeout=60.0)
                    # If we get here, we received a notification.
                    # Wait briefly to batch up rapid subsequent inserts
                    await asyncio.sleep(0.1)
                    # Clear all currently queued notifications
                    while not queue.empty():
                        queue.get_nowait()
                except TimeoutError:
                    # Failsafe timeout reached, proceed to sweep just in case
                    pass

                # Perform the sweep
                await relay_service.relay_pending_events()

            except Exception as e:
                logger.exception(f"Error in outbox relay daemon loop: {e}")
                if conn and not conn.is_closed():
                    await conn.close()
                    conn = None
                await asyncio.sleep(5)
    finally:
        if conn and not conn.is_closed():
            await conn.close()


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    # 1. Provisioning Consumer Setup
    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    outbox_adapter = SqsOutboxAdapter(queue_name=PROVISIONING_QUEUE_NAME)
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)
    provisioning_service = ProvisioningWorkerService(
        tenant_adapter, outbox_adapter, replication_adapter
    )

    # 2. Control Plane Relay Setup
    message_publisher = SqsPublisherAdapter(endpoint_url=settings.aws.endpoint_url)

    logger.info("Starting unified Enterprise Provisioning Worker (Relay + Provisioning)...")

    relay_task = asyncio.create_task(run_outbox_relay(db_router, message_publisher))
    provisioning_task = asyncio.create_task(run_worker(provisioning_service))

    try:
        await asyncio.gather(relay_task, provisioning_task)
    finally:
        logger.info("Shutting down worker tasks gracefully...")
        relay_task.cancel()
        provisioning_task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(relay_task, provisioning_task, return_exceptions=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
