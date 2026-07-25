import asyncio
import logging
import os

from config.settings import get_settings
from database.connection import DatabaseRouter

from worker.adapters.db_api_token import SqlAlchemyApiTokenAdapter
from worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from worker.adapters.sqs_outbox import SqsOutboxAdapter
from worker.adapters.sqs_ucp_listener import SqsUcpListenerAdapter
from worker.core.ucp_sync_service import UcpSyncWorkerService

logger = logging.getLogger(__name__)


async def run_worker(service: UcpSyncWorkerService) -> None:
    logger.info("Started UCP Sync Worker (Hexagonal Architecture)")
    while True:
        try:
            await service.process_messages()
        except Exception as e:
            logger.exception(f"Error in UCP sync loop: {e}")
            await asyncio.sleep(5)


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    endpoint_url = os.getenv("AWS_ENDPOINT_URL")

    # 1. Instantiate Adapters (Infrastructure Layer)
    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    api_token_adapter = SqlAlchemyApiTokenAdapter(db_router)

    # Existing adapter for pushing to internal sync queue
    sync_outbox_adapter = SqsOutboxAdapter(queue_name="edi.tenant.sync.fifo")

    # New adapter for polling UCP events
    ucp_listener_adapter = SqsUcpListenerAdapter(
        endpoint_url=endpoint_url,
        queue_name="ucp.events.fifo"
    )

    # 2. Instantiate Service (Core Business Logic) with strict Dependency Injection
    service = UcpSyncWorkerService(
        listener_port=ucp_listener_adapter,
        tenant_port=tenant_adapter,
        api_token_port=api_token_adapter,
        sync_outbox_port=sync_outbox_adapter,
    )

    # 3. Run
    await run_worker(service)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
