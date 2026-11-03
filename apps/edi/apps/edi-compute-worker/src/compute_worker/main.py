import asyncio

from dotenv import load_dotenv
from edi.bootstrap.container import (
    create_edi_control_plane_uow,
    create_edi_tenant_uow_provider,
)

load_dotenv()

import contextlib
from collections.abc import AsyncGenerator

import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.database.tenant_resolver import SqlAlchemyTenantResolver
from edi.adapters.outbound.transformer.bots_transformer_adapter import BotsTransformerAdapter
from edi.application.use_cases.pipeline.compute_outbound_transform_use_case import (
    ComputeOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase
from edi.bootstrap.publisher_factory import create_edi_pipeline_publisher
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.provider import PubSubProvider

from compute_worker.compute_dispatcher import EdiComputeDispatcher
from compute_worker.settings import get_settings

# Configure logging so it prints beautifully to the terminal
logger = structlog.get_logger("worker_runner")


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class EdiComputeWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.manager: SqsConsumerManager | None = None
        self.db_router: DatabaseRouter | None = None

    async def start(self) -> None:
        logger.info("compute_worker_initialization_started")
        settings = get_settings()
        aws_endpoint = settings.aws.endpoint_url
        s3_bucket = settings.s3.bucket

        self.db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )

        assert self.db_router is not None

        @contextlib.asynccontextmanager
        async def global_uow_factory() -> AsyncGenerator[ControlPlaneUnitOfWorkPort, None]:
            assert self.db_router is not None
            async with contextlib.aclosing(self.db_router.get_global_session()) as session_gen:
                async for session in session_gen:
                    yield create_edi_control_plane_uow(global_session=session)
                    break

        resolver = SqlAlchemyTenantResolver(self.db_router)

        transformer = BotsTransformerAdapter()

        uow_provider = create_edi_tenant_uow_provider(
            resolver=resolver,
            db_router=self.db_router,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
        )

        publisher = create_edi_pipeline_publisher(
            compute_queue_url=settings.sqs.compute_queue_url,
            orchestrator_queue_url=settings.sqs.orchestrator_queue_url,
            deliver_queue_url=settings.sqs.deliver_queue_url,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )

        async def use_case_factory(tenant_id: str) -> ComputeTransformUseCase:
            uow_factory = await uow_provider.get_uow_factory(tenant_id)
            return ComputeTransformUseCase(
                uow_factory=uow_factory,
                transformer=transformer,
                publisher=publisher,
            )

        async def outbound_use_case_factory(tenant_id: str) -> ComputeOutboundTransformUseCase:
            uow_factory = await uow_provider.get_uow_factory(tenant_id)
            return ComputeOutboundTransformUseCase(
                uow_factory=uow_factory,
                transformer=transformer,
                publisher=publisher,
            )

        dispatcher = EdiComputeDispatcher(
            use_case_factory=use_case_factory,
            outbound_use_case_factory=outbound_use_case_factory,
        )

        self.manager = PubSubProvider.create_consumer_manager(
            queue_url=settings.sqs.compute_queue_url,
            handler=dispatcher.dispatch_raw,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )
        assert self.manager is not None
        self.manager.start()
        logger.info("compute_worker_running")

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.manager and self.manager.task:
            return [self.manager.task]
        return []

    async def stop(self) -> None:
        logger.info("compute_worker_stopping")
        try:
            if self.manager:
                await self.manager.stop()
        finally:
            if self.db_router:
                await self.db_router.close_all()
        logger.info("compute_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("edi-compute-worker")
    module = EdiComputeWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
