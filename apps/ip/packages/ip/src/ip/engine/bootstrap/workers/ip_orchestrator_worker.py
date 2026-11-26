"""LaunchableWorker Composition Root for `ip-orchestrator-worker` (Layers 2, 3, and 4)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import structlog
from config_sync.application.multi_tenant_watch_manager import MultiTenantConfigWatchManager
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort
from config_sync.provider import ConfigSyncProvider
from database.router import DatabaseRouter, DatabaseRouterPort
from dependency_injector import providers
from pubsub.domain.enums import is_database_queue_uri
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from pubsub.ports.consumer_manager_port import ConsumerManagerPort
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.provider import PubSubProvider
from seedwork.events import EventProcessingLane
from seedwork.infra.worker import LaunchableWorker

from ip.engine.adapters.inbound.workers.ip_orchestrator_route_registry import (
    IpOrchestratorRouteRegistry,
)
from ip.engine.adapters.inbound.workers.ip_stitch_tick_loop import (
    IpMultiShardStitchTickLoop,
)
from ip.engine.adapters.outbound.config_sync.ip_stitch_catalog_sink import IpStitchCatalogSink
from ip.engine.application.use_cases.normalization.auto_bind_default_transformation_use_case import (
    AutoBindDefaultTransformationCommand,
    AutoBindDefaultTransformationOnEntitySubscribedUseCase,
    AutoBindDefaultTransformationResultDTO,
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
from ip.engine.application.use_cases.normalization.process_inbound_range_use_case import (
    ProcessInboundRangeCommand,
    ProcessInboundRangeResultDTO,
    ProcessInboundRangeUseCase,
)
from ip.engine.application.worker_ports import (
    IpAutoBindDefaultTransformationExecutorPort,
    IpBackfillStreamNormalizationExecutorPort,
    IpNormalizeReplicaExecutorPort,
    IpProcessInboundRangeExecutorPort,
)
from ip.engine.bootstrap.container import (
    Container,
    create_ip_control_plane_uow,
    create_ip_dp_filtered_outbox_drain_repo,
    create_ip_stitch_dispatcher,
    create_ip_stitch_worker_tick,
    create_ip_tenant_resolver,
)
from ip.engine.bootstrap.publisher_factory import IP_ORCHESTRATOR_DP_EVENT_TYPES
from ip.engine.domain.enums import IP_CONFIG_APP_ID
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.settings import IpEngineSettings, get_ip_engine_settings

logger = structlog.get_logger(__name__)


class _SessionScopedIpRangeExecutor(IpProcessInboundRangeExecutorPort):
    """Opens an isolated Control Plane GlobalSession per fused L2->L3 range execution."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: ProcessInboundRangeCommand
    ) -> Result[ProcessInboundRangeResultDTO, IpError]:
        async with self._db_router.global_session_scope() as global_session:
            cp_uow = create_ip_control_plane_uow(global_session)
            norm_uc = self._container.normalize_replica_record_use_case(
                control_plane_uow=cp_uow,
            )
            range_uc = ProcessInboundRangeUseCase(
                control_plane_uow=cp_uow,
                data_plane_uow_provider=self._container.dp_uow_provider(),
                normalize_use_case=norm_uc,
                extractor_registry=self._container.extractor_registry(),
                tiered_storage=self._container.tiered_storage(),
            )
            return await range_uc.execute(command)


class _SessionScopedIpNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    """Opens an isolated Control Plane GlobalSession per normalization execution."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        async with self._db_router.global_session_scope() as global_session:
            cp_uow = create_ip_control_plane_uow(global_session)
            use_case = self._container.normalize_replica_record_use_case(
                control_plane_uow=cp_uow,
            )
            return await use_case.execute(command)


class _SessionScopedIpBackfillExecutor(IpBackfillStreamNormalizationExecutorPort):
    """Opens an isolated Control Plane GlobalSession per stream normalization backfill."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        async with self._db_router.global_session_scope() as global_session:
            cp_uow = create_ip_control_plane_uow(global_session)
            norm_uc = self._container.normalize_replica_record_use_case(
                control_plane_uow=cp_uow,
            )
            backfill_uc = BackfillStreamNormalizationUseCase(
                data_plane_uow_provider=self._container.dp_uow_provider(),
                normalize_use_case=norm_uc,
            )
            return await backfill_uc.execute(command)


class _SessionScopedIpAutoBindTransformationExecutor(IpAutoBindDefaultTransformationExecutorPort):
    """Opens an isolated Control Plane GlobalSession per subscribed entity default transformation check."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: AutoBindDefaultTransformationCommand
    ) -> Result[AutoBindDefaultTransformationResultDTO, IpError]:
        async with self._db_router.global_session_scope() as global_session:
            cp_uow = create_ip_control_plane_uow(global_session)
            token_mgr = self._container.token_manager(control_plane_uow=cp_uow)
            discover_uc = self._container.discover_catalog_use_case(
                uow=cp_uow,
                token_manager=token_mgr,
            )
            auto_bind_uc = AutoBindDefaultTransformationOnEntitySubscribedUseCase(
                control_plane_uow=cp_uow,
                discover_catalog_use_case=discover_uc,
                transformer_registry=self._container.transformer_registry(),
            )
            return await auto_bind_uc.execute(command)


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
        container_configurator: Callable[[Container], object] | None = None,
    ) -> None:
        self._initial_settings = settings
        self.settings: IpEngineSettings | None = settings
        self._injected_db_router = db_router
        self.db_router: DatabaseRouterPort | None = db_router
        self._owns_db_router: bool = db_router is None
        self._realtime_consumer = realtime_consumer
        self._bulk_consumer = bulk_consumer
        self._container_configurator = container_configurator

        self.container: Container | None = None
        self.dispatcher: EventEnvelopeDispatcher | None = None
        self.route_registry: IpOrchestratorRouteRegistry | None = None
        self.realtime_manager: ConsumerManagerPort | None = None
        self.bulk_manager: ConsumerManagerPort | None = None
        self.cp_queue_manager: ConsumerManagerPort | None = None
        self.cp_bulk_queue_manager: ConsumerManagerPort | None = None
        self.stitch_tick_loop: IpMultiShardStitchTickLoop | None = None
        self.config_watch_manager: MultiTenantConfigWatchManager | None = None

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

        resolver = create_ip_tenant_resolver(self.db_router)
        container = Container()
        container.config.allow_private_ips.from_value(self.settings.allow_private_ips)
        container.config.max_delivery_attempts.from_value(self.settings.max_delivery_attempts)
        container.config.max_causation_depth.from_value(self.settings.max_causation_depth)
        container.db_router.override(providers.Object(self.db_router))
        container.tenant_resolver.override(providers.Object(resolver))
        if self._container_configurator is not None:
            self._container_configurator(container)
        self.container = container

        dp_uow_provider = container.dp_uow_provider()
        stitch_dispatcher = create_ip_stitch_dispatcher(
            db_router=self.db_router,
            dp_uow_provider=dp_uow_provider,
            stitch_catalog=container.stitch_catalog(),
            definition_registry=container.workflow_definition_registry(),
        )
        stitch_tick_adapter = create_ip_stitch_worker_tick(
            db_router=self.db_router,
            definition_registry=container.workflow_definition_registry(),
            handler_registry=container.step_handler_registry(),
        )

        self.route_registry = IpOrchestratorRouteRegistry(
            dp_uow_provider=dp_uow_provider,
            normalize_use_case=_SessionScopedIpNormalizeExecutor(self.db_router, container),
            backfill_use_case=_SessionScopedIpBackfillExecutor(self.db_router, container),
            auto_bind_transformation_use_case=_SessionScopedIpAutoBindTransformationExecutor(
                self.db_router, container
            ),
            process_inbound_range_use_case=_SessionScopedIpRangeExecutor(self.db_router, container),
            process_interval_batch_use_case=container.process_interval_batch_use_case(),
            extractor_registry=container.extractor_registry(),
            tiered_storage=container.tiered_storage(),
            stitch_dispatcher=stitch_dispatcher,
            stitch_worker_tick=stitch_tick_adapter,
            max_chunk_concurrency=self.settings.orchestrator_chunk_concurrency,
            max_causation_depth=self.settings.max_causation_depth,
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

        watch_base_url = self.settings.config_watch_base_url.strip()
        if watch_base_url:
            watch_token = self.settings.config_sync_internal_token.strip() or None
            lkg_dir = self.settings.config_watch_lkg_dir.strip()
            watch_client = ConfigSyncProvider.create_sse_watch_client(
                base_url=watch_base_url,
                bearer_token=watch_token,
            )
            stitch_catalog = container.stitch_catalog()

            def _create_ip_sink(tenant_id: str) -> ConfigApplySinkPort:
                lkg_path = Path(lkg_dir) / f"ip_config_{tenant_id}.json" if lkg_dir else None
                backing_sink = ConfigSyncProvider.create_in_memory_sink(
                    app_id=IP_CONFIG_APP_ID,
                    tenant_id=tenant_id,
                    lkg_file_path=lkg_path,
                )
                return IpStitchCatalogSink(
                    stitch_catalog=stitch_catalog,
                    backing_sink=backing_sink,
                    tenant_id=tenant_id,
                )

            self.config_watch_manager = ConfigSyncProvider.create_multi_tenant_watch_manager(
                app_id=IP_CONFIG_APP_ID,
                watch_client=watch_client,
                tenant_ids_provider=resolver.get_all_tenant_ids,
                sink_factory=_create_ip_sink,
                discovery_interval_seconds=self.settings.config_watch_tenant_discovery_sec,
            )
            self.config_watch_manager.start()
            logger.info(
                "ip_orchestrator_config_watch_started",
                watch_base_url=watch_base_url,
            )

        logger.info("ip_orchestrator_worker_started")

    def _start_queue_managers(
        self,
        settings: IpEngineSettings,
        dispatcher: EventEnvelopeDispatcher,
    ) -> None:
        if self._realtime_consumer is not None:
            self.realtime_manager = PubSubProvider.create_consumer_manager_for_consumer(
                consumer=self._realtime_consumer,
                handler=dispatcher.handle,
                queue_name="ip-orchestrator-realtime",
            )
            self.realtime_manager.start()
        elif settings.ip_orchestrator_realtime_queue_url:
            rt_uri = settings.ip_orchestrator_realtime_queue_url
            is_db_uri = is_database_queue_uri(rt_uri)
            rt_shard_repo = (
                create_ip_dp_filtered_outbox_drain_repo(
                    db_router=self.db_router,
                    event_types=IP_ORCHESTRATOR_DP_EVENT_TYPES,
                    lanes=(EventProcessingLane.REALTIME.value,),
                )
                if self.db_router is not None and is_db_uri
                else None
            )
            self.realtime_manager = PubSubProvider.create_consumer_manager(
                source_uri=rt_uri,
                handler=dispatcher.handle,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
                transport=settings.pubsub_transport,
                shard_drain_repo=rt_shard_repo,
                batch_size=settings.outbox_batch_size,
                lock_lease_ms=settings.outbox_lock_lease_ms,
            )
            self.realtime_manager.start()

            if is_db_uri:
                self.cp_queue_manager = PubSubProvider.create_consumer_manager(
                    source_uri=rt_uri,
                    handler=dispatcher.handle,
                    transport=settings.pubsub_transport,
                    session_factory=(
                        self.db_router.global_session_scope if self.db_router is not None else None
                    ),
                    database_url=settings.global_database_url,
                    batch_size=settings.outbox_batch_size,
                    lock_lease_ms=settings.outbox_lock_lease_ms,
                )
                self.cp_queue_manager.start()

        if self._bulk_consumer is not None:
            self.bulk_manager = PubSubProvider.create_consumer_manager_for_consumer(
                consumer=self._bulk_consumer,
                handler=dispatcher.handle,
                queue_name="ip-orchestrator-bulk",
            )
            self.bulk_manager.start()
        elif settings.ip_orchestrator_bulk_queue_url:
            bulk_uri = settings.ip_orchestrator_bulk_queue_url
            is_bulk_db_uri = is_database_queue_uri(bulk_uri)
            bulk_shard_repo = (
                create_ip_dp_filtered_outbox_drain_repo(
                    db_router=self.db_router,
                    event_types=IP_ORCHESTRATOR_DP_EVENT_TYPES,
                    lanes=(EventProcessingLane.BULK.value,),
                )
                if self.db_router is not None and is_bulk_db_uri
                else None
            )
            self.bulk_manager = PubSubProvider.create_consumer_manager(
                source_uri=bulk_uri,
                handler=dispatcher.handle,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
                transport=settings.pubsub_transport,
                shard_drain_repo=bulk_shard_repo,
                batch_size=settings.outbox_batch_size,
                lock_lease_ms=settings.outbox_lock_lease_ms,
            )
            self.bulk_manager.start()

            if is_bulk_db_uri:
                self.cp_bulk_queue_manager = PubSubProvider.create_consumer_manager(
                    source_uri=bulk_uri,
                    handler=dispatcher.handle,
                    transport=settings.pubsub_transport,
                    session_factory=(
                        self.db_router.global_session_scope if self.db_router is not None else None
                    ),
                    database_url=settings.global_database_url,
                    batch_size=settings.outbox_batch_size,
                    lock_lease_ms=settings.outbox_lock_lease_ms,
                )
                self.cp_bulk_queue_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.realtime_manager is not None:
            tasks.extend(self.realtime_manager.background_tasks())
        if self.cp_queue_manager is not None:
            tasks.extend(self.cp_queue_manager.background_tasks())
        if self.bulk_manager is not None:
            tasks.extend(self.bulk_manager.background_tasks())
        if self.cp_bulk_queue_manager is not None:
            tasks.extend(self.cp_bulk_queue_manager.background_tasks())
        if self.stitch_tick_loop is not None:
            tasks.extend(self.stitch_tick_loop.background_tasks())
        if self.config_watch_manager is not None:
            tasks.extend(self.config_watch_manager.background_tasks())
        return tasks

    async def stop(self) -> None:
        logger.info("ip_orchestrator_worker_stopping")
        if self.config_watch_manager is not None:
            await self.config_watch_manager.stop()
            self.config_watch_manager = None
        if self.stitch_tick_loop is not None:
            await self.stitch_tick_loop.stop()
        if self.cp_bulk_queue_manager is not None:
            await self.cp_bulk_queue_manager.stop()
        if self.cp_queue_manager is not None:
            await self.cp_queue_manager.stop()
        if self.realtime_manager is not None:
            await self.realtime_manager.stop()
        if self.bulk_manager is not None:
            await self.bulk_manager.stop()
        if self.db_router is not None and self._owns_db_router:
            await self.db_router.close_all()
        logger.info("ip_orchestrator_worker_stopped")


__all__ = ["IpOrchestratorWorkerModule"]
