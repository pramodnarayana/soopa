import asyncio

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.database.replication_adapter import SqlAlchemyReplicationAdapter
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from observability import ObservabilityProvider
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from config_sync_worker.adapters.acl.registry import DefaultEventTranslator
from config_sync_worker.adapters.inbound.workers.edi_config_sync_sqs_dispatcher import (
    EdiConfigSyncSqsDispatcher,
)
from config_sync_worker.application.service import ProvisioningWorkerService
from config_sync_worker.provision.settings import get_settings

load_dotenv()

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class EdiConfigSyncWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.db_router: DatabaseRouter | None = None
        self.sqs_manager: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("config_sync_worker_starting")
        settings = get_settings()
        self.db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )
        assert self.db_router is not None
        tenant_adapter = TenantResolver(self.db_router)
        replication_adapter = SqlAlchemyReplicationAdapter(self.db_router, tenant_adapter)

        logger.info("starting_unified_provisioning_worker")

        # 1. AWS SQS Consumer (Data Plane Replication)
        logger.info("initializing_sqs_consumer")
        translator = DefaultEventTranslator()
        replication_service = ProvisioningWorkerService(tenant_adapter, replication_adapter)
        dispatcher = EdiConfigSyncSqsDispatcher(
            domain_service=replication_service, transformer_port=translator
        )

        provisioning_consumer = AwsSqsConsumer(
            queue_url=settings.sqs.provisioning_queue_url,
            region_name=settings.aws.resolved_region,
            endpoint_url=settings.aws.endpoint_url,
        )
        self.sqs_manager = SqsConsumerManager(
            consumer=provisioning_consumer,
            queue_name=settings.sqs.provisioning_queue_url.rsplit("/", 1)[-1],
            handler=dispatcher.dispatch_raw,
        )
        assert self.sqs_manager is not None
        self.sqs_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.sqs_manager and self.sqs_manager.task:
            return [self.sqs_manager.task]
        return []

    async def stop(self) -> None:
        logger.info("shutting_down_gracefully")
        if self.sqs_manager:
            await self.sqs_manager.stop()

        # Close adapter resources
        if self.db_router:
            await self.db_router.close_all()


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("config-sync-worker")
    module = EdiConfigSyncWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
