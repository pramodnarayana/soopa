import asyncio

import structlog
from config.settings import get_settings
from database.connection import DatabaseRouter
from dotenv import load_dotenv

from worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from worker.adapters.listen_notify_outbox_adapter import ListenNotifyOutboxAdapter
from worker.adapters.sqs_outbox import SqsOutboxAdapter
from worker.core.service import ProvisioningWorkerService

load_dotenv()

logger = structlog.get_logger(__name__)

PROVISIONING_QUEUE_NAME = "edi-tenant-sync.fifo"


async def run_worker(service: ProvisioningWorkerService, name: str) -> None:
    bound_logger = logger.bind(worker_name=name)
    bound_logger.info("worker_started")

    async def _poll_loop() -> None:
        while True:
            try:
                processed_event = await service.process_next_event()
                # If no event was processed, yield/sleep briefly
                if not processed_event:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except Exception:
                bound_logger.exception("provisioning_loop_error")
                await asyncio.sleep(5)

    try:
        if hasattr(service.outbox_port, "__aenter__"):
            async with service.outbox_port:  # type: ignore
                await _poll_loop()
        else:
            await _poll_loop()
    except asyncio.CancelledError:
        pass


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)

    # 1. Internal DB Listener (Postgres LISTEN/NOTIFY)
    logger.info("initializing_internal_postgres_listener")
    internal_outbox = ListenNotifyOutboxAdapter(db_url=settings.database.global_url)
    internal_service = ProvisioningWorkerService(
        tenant_adapter, internal_outbox, replication_adapter
    )

    # 2. AWS SQS Consumer
    logger.info("initializing_aws_sqs_consumer")
    aws_outbox = SqsOutboxAdapter(queue_name=PROVISIONING_QUEUE_NAME)
    aws_service = ProvisioningWorkerService(tenant_adapter, aws_outbox, replication_adapter)

    logger.info("starting_unified_provisioning_worker")

    internal_task = asyncio.create_task(run_worker(internal_service, "InternalListener"))
    aws_task = asyncio.create_task(run_worker(aws_service, "AwsListener"))

    from worker.provision.outbox_sweeper import run_sweeper

    sweeper_task = asyncio.create_task(run_sweeper(settings.database.global_url, internal_outbox))

    try:
        await asyncio.gather(internal_task, aws_task, sweeper_task)
    finally:
        logger.info("shutting_down_gracefully")
        internal_task.cancel()
        aws_task.cancel()
        sweeper_task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(internal_task, aws_task, sweeper_task, return_exceptions=True)

        # Close adapter resources
        await internal_outbox.close()
        await aws_outbox.close()


if __name__ == "__main__":
    asyncio.run(main())
