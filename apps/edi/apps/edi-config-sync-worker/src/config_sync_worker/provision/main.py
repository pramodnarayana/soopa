import asyncio
import signal
from typing import Any

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.config.settings import get_settings
from edi.domain.events import MessageQueueName
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from config_sync_worker.adapters.acl.registry import DefaultEventTranslator
from config_sync_worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from config_sync_worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from config_sync_worker.adapters.inbound.workers.edi_config_sync_sqs_dispatcher import (
    EdiConfigSyncSqsDispatcher,
)
from config_sync_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_repository import (
    PostgresEdiControlPlaneOutboxRepository,
)
from config_sync_worker.domain.service import ProvisioningWorkerService

load_dotenv()

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)

    logger.info("starting_unified_provisioning_worker")

    # 1. AWS SQS Consumer (Data Plane Replication)
    logger.info("initializing_sqs_consumer")
    translator = DefaultEventTranslator()
    replication_service = ProvisioningWorkerService(tenant_adapter, replication_adapter)
    dispatcher = EdiConfigSyncSqsDispatcher(
        domain_service=replication_service, translator_port=translator
    )

    provisioning_consumer = AwsSqsConsumer(
        queue_url=settings.sqs.provisioning_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )
    sqs_manager = SqsConsumerManager(
        consumer=provisioning_consumer,
        queue_name=MessageQueueName.PROVISIONING_QUEUE.value,
        handler=dispatcher.dispatch_raw,
    )
    sqs_manager.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
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

            # Wait for stop signal, or if sqs_manager/outbox_listener fails
            manager_task = sqs_manager.task
            tasks_to_wait: list[asyncio.Task[Any]] = [asyncio.create_task(stop_event.wait())]
            if manager_task:
                tasks_to_wait.append(manager_task)

            done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)

            # If the manager task completed with an exception, re-raise it
            for task in done:
                if task is manager_task and task.exception():
                    exc = task.exception()
                    logger.error("sqs_consumer_manager_failed", exc_info=exc)
                    if exc:
                        raise exc

    finally:
        logger.info("shutting_down_gracefully")
        await sqs_manager.stop()
        await outbox_listener.stop()

        # Close adapter resources
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
