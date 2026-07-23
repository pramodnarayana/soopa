import asyncio
import logging

from config.settings import get_settings
from database.connection import DatabaseRouter
from dotenv import load_dotenv
from worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from worker.adapters.sqs_outbox import SqsOutboxAdapter
from worker.core.service import ProvisioningWorkerService

load_dotenv()

logger = logging.getLogger(__name__)


async def run_worker(service: ProvisioningWorkerService) -> None:
    logger.info("Started polling Database for PROVISION events")
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


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    outbox_adapter = SqsOutboxAdapter(queue_name="edi.tenant.sync.fifo")
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)

    service = ProvisioningWorkerService(tenant_adapter, outbox_adapter, replication_adapter)

    await run_worker(service)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
