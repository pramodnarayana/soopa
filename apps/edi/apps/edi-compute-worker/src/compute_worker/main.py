import asyncio
import signal

from dotenv import load_dotenv
from edi.adapters.outbound.database.control_plane.uow import SqlAlchemyControlPlaneUnitOfWork

load_dotenv()

import contextlib
from collections.abc import AsyncGenerator

import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.adapters.outbound.database.tenant_uow_provider import TenantUowProvider
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.compute_outbound_transform_use_case import (
    ComputeOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase
from edi.config.settings import get_settings
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from observability import ObservabilityProvider
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from compute_worker.compute_dispatcher import EdiComputeDispatcher

# Configure logging so it prints beautifully to the terminal
logger = structlog.get_logger("worker_runner")


from seedwork.infra.worker import LaunchableWorker


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
                    yield SqlAlchemyControlPlaneUnitOfWork(global_session=session)
                    break

        resolver = TenantResolver(self.db_router)

        transformer = BotsTransformerAdapter()

        uow_provider = TenantUowProvider(
            resolver=resolver,
            db_router=self.db_router,
            settings=settings,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
        )

        async def use_case_factory(tenant_id: str) -> ComputeTransformUseCase:
            uow_factory = await uow_provider.get_uow_factory(tenant_id)
            return ComputeTransformUseCase(
                uow_factory=uow_factory,
                transformer=transformer,
            )

        async def outbound_use_case_factory(tenant_id: str) -> ComputeOutboundTransformUseCase:
            uow_factory = await uow_provider.get_uow_factory(tenant_id)
            return ComputeOutboundTransformUseCase(
                uow_factory=uow_factory,
                transformer=transformer,
            )

        dispatcher = EdiComputeDispatcher(
            use_case_factory=use_case_factory,
            outbound_use_case_factory=outbound_use_case_factory,
        )

        compute_consumer = AwsSqsConsumer(
            queue_url=settings.sqs.compute_queue_url,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )
        self.manager = SqsConsumerManager(
            consumer=compute_consumer,
            queue_name=settings.sqs.compute_queue_url.rsplit("/", 1)[-1],
            handler=dispatcher.dispatch_raw,
        )
        assert self.manager is not None
        self.manager.start()
        logger.info("compute_worker_running")

    async def stop(self) -> None:
        logger.info("compute_worker_stopping")
        try:
            if self.manager:
                await self.manager.stop()
        finally:
            if self.db_router:
                await self.db_router.close_all()
        logger.info("compute_worker_stopped")


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("edi-compute-worker")

    module = EdiComputeWorkerModule()

    try:
        await module.start()

        # Handle shutdown signals
        loop = asyncio.get_running_loop()

        stop_event = asyncio.Event()

        def shutdown_handler(*args: object) -> None:
            logger.info("compute_worker_shutdown_signal_received")
            stop_event.set()

        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

        await stop_event.wait()
    finally:
        await module.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("compute_worker_stopped_by_user")
