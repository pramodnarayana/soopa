"""LaunchableWorker entrypoint for `ip-orchestrator-worker` (Layers 2, 3, and 4)."""

from __future__ import annotations

import asyncio
from typing import cast

import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from dependency_injector import providers
from ip.engine.adapters.inbound.workers.ip_orchestrator_route_registry import (
    IpOrchestratorRouteRegistry,
)
from ip.engine.adapters.inbound.workers.ip_stitch_tick_loop import (
    IpMultiShardStitchTickLoop,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationResultDTO,
    BackfillStreamNormalizationUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
)
from ip.engine.application.worker_ports import (
    IpBackfillStreamNormalizationExecutorPort,
    IpNormalizeReplicaExecutorPort,
)
from ip.engine.container import Container, create_ip_workflow_uow
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.settings import IpEngineSettings, get_ip_engine_settings
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.provider import PubSubProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

logger = structlog.get_logger(__name__)


class _SessionScopedIpNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    """Opens an isolated Control Plane GlobalSession per normalization execution."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        async for global_session in self._db_router.get_global_session():
            cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
            use_case = self._container.normalize_replica_record_use_case(
                control_plane_uow=cp_uow,
            )
            return await use_case.execute(command)
        raise RuntimeError("DatabaseRouter did not yield a GlobalSession.")


class _SessionScopedIpBackfillExecutor(IpBackfillStreamNormalizationExecutorPort):
    """Opens an isolated Control Plane GlobalSession per stream normalization backfill."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        async for global_session in self._db_router.get_global_session():
            cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
            norm_uc = self._container.normalize_replica_record_use_case(
                control_plane_uow=cp_uow,
            )
            backfill_uc = BackfillStreamNormalizationUseCase(
                data_plane_uow_provider=self._container.dp_uow_provider(),
                normalize_use_case=norm_uc,
            )
            return await backfill_uc.execute(command)
        raise RuntimeError("DatabaseRouter did not yield a GlobalSession.")


class IpOrchestratorWorkerModule(LaunchableWorker):
    """Physical worker bulkhead for IP internal data pipeline orchestration (L2, L3, L4).

    Consumes from both the `realtime` ($N=1$) and `bulk` ($N=K$) orchestrator SQS queues
    and runs the background `IpMultiShardStitchTickLoop`.
    """

    def __init__(
        self,
        settings: IpEngineSettings | None = None,
        *,
        db_router: DatabaseRouterPort | None = None,
        realtime_consumer: MessageConsumerPort | None = None,
        bulk_consumer: MessageConsumerPort | None = None,
    ) -> None:
        self._initial_settings = settings
        self.settings: IpEngineSettings | None = settings
        self._injected_db_router = db_router
        self.db_router: DatabaseRouterPort | None = db_router
        self._owns_db_router: bool = db_router is None
        self._realtime_consumer = realtime_consumer
        self._bulk_consumer = bulk_consumer

        self.container: Container | None = None
        self.dispatcher: EventEnvelopeDispatcher | None = None
        self.route_registry: IpOrchestratorRouteRegistry | None = None
        self.realtime_manager: SqsConsumerManager | None = None
        self.bulk_manager: SqsConsumerManager | None = None
        self.stitch_tick_loop: IpMultiShardStitchTickLoop | None = None

    async def start(self) -> None:
        logger.info("ip_orchestrator_worker_starting")
        self.settings = self._initial_settings or get_ip_engine_settings()

        if self.db_router is None:
            self.db_router = DatabaseRouter(
                global_db_url=self.settings.global_database_url,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
            )
            self._owns_db_router = True

        resolver = IpTenantResolver(self.db_router)
        container = Container()
        container.config.allow_private_ips.from_value(self.settings.allow_private_ips)
        container.db_router.override(providers.Object(self.db_router))
        container.tenant_resolver.override(providers.Object(resolver))
        self.container = container

        dp_uow_provider = container.dp_uow_provider()
        stitch_dispatcher = IpStitchCanonicalDispatcherAdapter(
            db_router=self.db_router,
            dp_uow_provider=dp_uow_provider,
            stitch_catalog=container.stitch_catalog(),
            definition_registry=container.workflow_definition_registry(),
            workflow_uow_factory=create_ip_workflow_uow,
            control_plane_uow_factory=SqlAlchemyIpControlPlaneUnitOfWork,
        )
        stitch_tick_adapter = IpStitchWorkerTickAdapter(
            db_router=self.db_router,
            definition_registry=container.workflow_definition_registry(),
            handler_registry=container.step_handler_registry(),
            workflow_uow_factory=create_ip_workflow_uow,
        )

        self.route_registry = IpOrchestratorRouteRegistry(
            dp_uow_provider=dp_uow_provider,
            normalize_use_case=_SessionScopedIpNormalizeExecutor(self.db_router, container),
            backfill_use_case=_SessionScopedIpBackfillExecutor(self.db_router, container),
            extractor_registry=container.extractor_registry(),
            tiered_storage=container.tiered_storage(),
            stitch_dispatcher=stitch_dispatcher,
            stitch_worker_tick=stitch_tick_adapter,
            max_chunk_concurrency=self.settings.orchestrator_chunk_concurrency,
        )
        self.dispatcher = EventEnvelopeDispatcher()
        self.route_registry.register_routes(self.dispatcher)

        self._start_queue_managers(self.settings, self.dispatcher)

        self.stitch_tick_loop = IpMultiShardStitchTickLoop(
            tick_executor=stitch_tick_adapter,
            free_slots=self.settings.orchestrator_chunk_concurrency,
            interval_seconds=self.settings.stitch_tick_interval_sec,
        )
        self.stitch_tick_loop.start()
        logger.info("ip_orchestrator_worker_started")

    def _start_queue_managers(
        self,
        settings: IpEngineSettings,
        dispatcher: EventEnvelopeDispatcher,
    ) -> None:
        if self._realtime_consumer is not None:
            self.realtime_manager = SqsConsumerManager(
                consumer=self._realtime_consumer,
                handler=dispatcher.handle,
                queue_name="ip-orchestrator-realtime",
            )
            self.realtime_manager.start()
        elif settings.ip_orchestrator_realtime_queue_url:
            self.realtime_manager = PubSubProvider.create_consumer_manager(
                queue_url=settings.ip_orchestrator_realtime_queue_url,
                handler=dispatcher.handle,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            self.realtime_manager.start()

        if self._bulk_consumer is not None:
            self.bulk_manager = SqsConsumerManager(
                consumer=self._bulk_consumer,
                handler=dispatcher.handle,
                queue_name="ip-orchestrator-bulk",
            )
            self.bulk_manager.start()
        elif settings.ip_orchestrator_bulk_queue_url:
            self.bulk_manager = PubSubProvider.create_consumer_manager(
                queue_url=settings.ip_orchestrator_bulk_queue_url,
                handler=dispatcher.handle,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            self.bulk_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.realtime_manager is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.realtime_manager.background_tasks()))
        if self.bulk_manager is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.bulk_manager.background_tasks()))
        if self.stitch_tick_loop is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.stitch_tick_loop.background_tasks()))
        return tasks

    async def stop(self) -> None:
        logger.info("ip_orchestrator_worker_stopping")
        if self.stitch_tick_loop is not None:
            await self.stitch_tick_loop.stop()
        if self.realtime_manager is not None:
            await self.realtime_manager.stop()
        if self.bulk_manager is not None:
            await self.bulk_manager.stop()
        if self.db_router is not None and self._owns_db_router:
            await self.db_router.close_all()
        logger.info("ip_orchestrator_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("ip-orchestrator-worker")
    module = IpOrchestratorWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)

__all__ = ["IpOrchestratorWorkerModule", "main"]
