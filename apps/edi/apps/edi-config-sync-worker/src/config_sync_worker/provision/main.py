import asyncio

import structlog
from dotenv import load_dotenv
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.config.settings import get_settings
from edi.domain.events import MessageQueueName
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher

from config_sync_worker.adapters.acl.registry import DefaultEventTranslator
from config_sync_worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from config_sync_worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from config_sync_worker.adapters.inbound.workers.edi_config_sync_sqs_consumer import (
    EdiConfigSyncSqsConsumer,
)
from config_sync_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_repository import (
    PostgresEdiControlPlaneOutboxRepository,
)
from config_sync_worker.domain.service import ProvisioningWorkerService

load_dotenv()

logger = structlog.get_logger(__name__)


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
            async with service.outbox_port:
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

    logger.info("starting_unified_provisioning_worker")

    # 1. AWS SQS Consumer (Data Plane Replication)
    logger.info("initializing_sqs_consumer")
    sqs_outbox = EdiConfigSyncSqsConsumer(
        queue_name=MessageQueueName.PROVISIONING_QUEUE.value,
        endpoint_url=settings.aws.endpoint_url,
        region=settings.aws.default_region,
    )
    translator = DefaultEventTranslator()
    replication_service = ProvisioningWorkerService(
        tenant_adapter, sqs_outbox, replication_adapter, translator
    )
    replication_task = asyncio.create_task(
        run_worker(replication_service, "EdiDataPlaneReplicationWorker")
    )

    # Instantiate Adapters for Outbox Relay
    outbox_relay_repository = PostgresEdiControlPlaneOutboxRepository(db_router=db_router)
    outbox_relay_publisher = AwsSnsPublisher(
        topic_arn=settings.aws.sns_topic_arn,
        endpoint_url=settings.aws.endpoint_url,
        region_name=settings.aws.default_region,
    )

    # 2. Outbox Processor & Postgres Listener (Control Plane)
    logger.info("initializing_outbox_processor_and_listener")
    outbox_processor = OutboxProcessorUseCase(
        repository=outbox_relay_repository,
        publisher=outbox_relay_publisher,
    )
    outbox_listener = PostgresOutboxRelay(
        listen_channel="edi_outbox_channel",
        processor=outbox_processor,
        database_url=settings.database.global_url,
    )

    try:
        async with outbox_relay_publisher:
            outbox_listener.start()
            await replication_task
    finally:
        logger.info("shutting_down_gracefully")
        replication_task.cancel()
        await outbox_listener.stop()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(replication_task, return_exceptions=True)

        # Close adapter resources
        await sqs_outbox.close()


if __name__ == "__main__":
    asyncio.run(main())
