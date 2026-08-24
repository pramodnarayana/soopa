import asyncio
import os

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.config.settings import get_settings

from worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from worker.adapters.edi_config_sync_sqs_consumer import EdiConfigSyncSqsConsumer
from worker.adapters.edi_sqs_consumer import EdiSqsConsumer
from worker.application.use_cases.ucp_sync_service import UcpSyncWorkerService

logger = structlog.get_logger(__name__)


async def run_worker(service: UcpSyncWorkerService) -> None:
    logger.info("Started UCP Sync Worker (Hexagonal Architecture)")
    while True:
        try:
            await service.process_messages()
        except Exception:
            logger.exception("Error in UCP sync loop")

            await asyncio.sleep(5)


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    endpoint_url = os.getenv("AWS_ENDPOINT_URL")

    # 1. Instantiate Adapters (Infrastructure Layer)
    tenant_adapter = SqlAlchemyTenantAdapter(db_router)

    # Existing adapter for pushing to internal sync queue
    sync_outbox_adapter = EdiSqsConsumer(queue_name="edi-tenant-sync.fifo")

    # New adapter for polling UCP events
    ucp_listener_adapter = EdiConfigSyncSqsConsumer(
        endpoint_url=endpoint_url, queue_name="edi-config-sync.fifo"
    )

    # 2. Instantiate Service (Core Business Logic) with strict Dependency Injection
    service = UcpSyncWorkerService(
        listener_port=ucp_listener_adapter,
        tenant_port=tenant_adapter,
        sync_outbox_port=sync_outbox_adapter,
    )

    # 3. Register UCP Job Handlers
    # (Removed: UCP Outbox Sweeper and Data Retention are now strictly handled by ucp-worker)

    # 4. Run tasks
    sync_task = asyncio.create_task(run_worker(service))

    try:
        await asyncio.gather(sync_task)
    finally:
        logger.info("Shutting down UCP sync worker tasks gracefully...")
        sync_task.cancel()

        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(sync_task, return_exceptions=True)

        if db_router:
            await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
