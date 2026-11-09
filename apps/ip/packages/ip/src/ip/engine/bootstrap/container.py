"""Declarative IoC Container and Composition Root factories for the Integration Platform (IP) Engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from database.provider import DatabaseProvider
from database.router import DatabaseRouterPort
from dependency_injector import containers, providers
from orchestration.application.services import InMemoryWorkflowDefinitionRegistry
from orchestration.application.services.registries import (
    InMemoryPredicateRegistry,
    InMemoryStepHandlerRegistry,
)
from orchestration.bootstrap import create_workflow_uow
from orchestration.ports.inbound.step_handler_port import (
    StepHandlerRegistryPort,
    WorkflowDefinitionRegistryPort,
)
from orchestration.ports.outbound import WorkflowUnitOfWorkPort
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import MultiShardOutboxDrainRelay
from outbox.adapters.inbound.notify_outbox_relay import NotifyOutboxRelay
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_relay_port import OutboxRelayPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from outbox.ports.shard_outbox_drain_port import ShardOutboxDrainPort
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider
from shttp import HttpRequestAuthenticator
from sqlalchemy.ext.asyncio import AsyncSession
from storage.provider import StorageProvider
from strace.adapters import SqlAlchemyTraceRepository
from strace.adapters.retention_repository import SqlAlchemyShardedTraceRetentionRepository
from strace.ports.retention_repository_port import TraceRetentionRepositoryPort

from ip.engine.adapters.outbound.auth.oauth2_strategy import (
    OAuth2StrategyTokenRefresher,
)
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    SqlAlchemyTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.adapters.outbound.connectors.generic_http_connector import GenericHttpConnector
from ip.engine.adapters.outbound.connectors.sftp_connector import SftpConnector
from ip.engine.adapters.outbound.database.control_plane.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stitch_repository import (
    SqlAlchemyStitchRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stream_state_repository import (
    SqlAlchemyStreamStateRepository,
)
from ip.engine.adapters.outbound.database.control_plane.sync_run_repository import (
    SqlAlchemySyncRunRepository,
)
from ip.engine.adapters.outbound.database.control_plane.transformation_repository import (
    SqlAlchemyTransformationRepository,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.batch_manifest_repository import (
    SqlAlchemyBatchManifestRepository,
)
from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_ledger_repository import (
    SqlAlchemyNormalizationLedgerRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_rejection_repository import (
    SqlAlchemyNormalizationRejectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalized_record_repository import (
    SqlAlchemyNormalizedRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.pending_reference_repository import (
    SqlAlchemyPendingReferenceRepository,
)
from ip.engine.adapters.outbound.database.data_plane.quarantine_record_repository import (
    SqlAlchemyQuarantineRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_rejection_repository import (
    SqlAlchemyReplicaRejectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.trace_specs import (
    IP_TRACE_EVENT_SPEC,
    IP_TRACE_STAGE_SPECS,
    stage_workflow_outbox_event,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpProcessedEventModel,
    IpTraceEventModel,
)
from ip.engine.adapters.outbound.database.tenant_resolver import SqlAlchemyIpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import SqlAlchemyIpTenantUoWProvider
from ip.engine.adapters.outbound.inbound.ack import StandardInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import NoOpVerifier
from ip.engine.adapters.outbound.intervals.interval_batch_normalizer import (
    VectorizedIntervalBatchNormalizerAdapter,
)
from ip.engine.adapters.outbound.intervals.interval_rollup_repository import (
    ColumnarIntervalRollupRepositoryAdapter,
)
from ip.engine.adapters.outbound.stitches.step_handlers import (
    EmitNotificationStepHandler,
    ExecuteHttpActionStepHandler,
    OutboundDeliveryStagerPort,
    OutboundRecordLookupPort,
    QueryReplicaStepHandler,
    TenantAwareNotificationOutboxAdapter,
    TenantAwareOutboundRecordLookupAdapter,
    TenantAwareReplicaLookupAdapter,
)
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
)
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    DEFAULT_IP_PAYLOAD_BUCKET,
    TieredStorageAdapter,
)
from ip.engine.application.use_cases.connections.discover_catalog_use_case import (
    DiscoverCatalogUseCase,
)
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordResponse,
    DeliverOutboundRecordUseCase,
)
from ip.engine.application.use_cases.delivery.replay_deliver_stage import (
    DeliverStageReplayProcessor,
)
from ip.engine.application.use_cases.delivery.stage_outbound_delivery_use_case import (
    StageOutboundDeliveryCommand,
    StageOutboundDeliveryResponse,
    StageOutboundDeliveryUseCase,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordUseCase,
)
from ip.engine.application.use_cases.ingestion.replay_ingest_stage import (
    IngestStageReplayProcessor,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncUseCase,
)
from ip.engine.application.use_cases.intervals.buffer_raw_interval_batch_use_case import (
    BufferRawIntervalBatchUseCase,
)
from ip.engine.application.use_cases.intervals.interval_rollup_use_cases import (
    GetBatchReconciliationSummaryUseCase,
    GetDailyCompletenessUseCase,
    GetDailyTouRollupsUseCase,
    RecordSettlementReceiptUseCase,
    TraceIntervalLineageUseCase,
)
from ip.engine.application.use_cases.intervals.process_interval_batch_use_case import (
    ProcessIntervalBatchUseCase,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationUseCase,
)
from ip.engine.application.use_cases.normalization.bind_stream_transformation_use_case import (
    BindStreamTransformationUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.normalization.process_inbound_range_use_case import (
    ProcessInboundRangeUseCase,
)
from ip.engine.application.use_cases.normalization.promote_transformation_version_use_case import (
    PromoteTransformationVersionUseCase,
)
from ip.engine.application.use_cases.normalization.replay_normalize_stage import (
    NormalizeStageReplayProcessor,
)
from ip.engine.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageUseCase,
)
from ip.engine.application.use_cases.replay.modify_and_replay_use_case import (
    ModifyAndReplayUseCase,
)
from ip.engine.application.use_cases.replay.replay_stage_use_case import (
    ReplayStageUseCase,
)
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicateRecordsUseCase,
)
from ip.engine.application.use_cases.replication.sweep_stale_replicas_use_case import (
    SweepStaleReplicasUseCase,
)
from ip.engine.application.use_cases.stitch.replay_stitch_stage import (
    StitchStageReplayProcessor,
)
from ip.engine.application.use_cases.trace.get_ip_trace_lineage_use_case import (
    GetIpTraceLineageUseCase,
)
from ip.engine.application.use_cases.trace.get_ip_trace_use_case import (
    GetIpTraceUseCase,
)
from ip.engine.application.worker_ports import (
    IpOutboundDeliveryExecutorPort,
    IpStitchWorkerTickExecutorPort,
)
from ip.engine.bootstrap.publisher_factory import (
    create_ip_cp_outbox_publisher,
    create_ip_dp_outbox_publisher,
)
from ip.engine.domain.connection.enums import (
    AuthType,
    CatalogCategory,
    ConnectorArchitectureType,
    EngineConnectorId,
)
from ip.engine.domain.constants import (
    DEFAULT_MAX_CAUSATION_DEPTH,
    DEFAULT_MAX_DELIVERY_ATTEMPTS,
)
from ip.engine.domain.enums import IpOutboxSource, PipelineStage
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.normalization.policies import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.normalization.registries import (
    CanonicalEntityRegistry,
    CanonicalWriterRegistry,
    TransformerRegistry,
)
from ip.engine.ports.outbound.auth_resolver_port import AuthStrategyResolverPort
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.catalog_registry_port import (
    CatalogAppSummaryDTO,
    CatalogConnectorMapping,
)
from ip.engine.ports.outbound.columnar_batch_processor_port import ColumnarBatchProcessorPort
from ip.engine.ports.outbound.connector_port import ConnectorPort, DestinationConnectorPort
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.interval_rollup_repository_port import IntervalRollupRepositoryPort
from ip.engine.ports.outbound.record_extractor_port import RecordExtractorRegistry
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    TokenRefreshLockPort,
)
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkProviderPort,
    IpTenantResolverPort,
)
from ip.engine.settings import IpEngineSettings

DomainRepositoryFactory = Callable[[AsyncSession], object]


def create_engine_catalog_registry(
    allow_private_ips: bool = False,
    *,
    auth_resolver: AuthStrategyResolverPort[HttpRequestAuthenticator] | None = None,
) -> ConnectorCatalogRegistry:
    """Creates a pure domain-agnostic catalog registry pre-seeded only with standard protocol transports."""
    resolved_auth_resolver = auth_resolver or AuthStrategyResolver()
    registry = ConnectorCatalogRegistry(
        auth_resolver=resolved_auth_resolver,
        allow_private_ips=allow_private_ips,
    )
    http_conn = GenericHttpConnector(
        app_id=EngineConnectorId.HTTP,
        auth_resolver=resolved_auth_resolver,
        allow_private_ips=allow_private_ips,
    )
    registry.register_connector(
        http_conn,
        CatalogAppSummaryDTO(
            app_id=EngineConnectorId.HTTP,
            display_name="HTTP / REST API",
            category=CatalogCategory.API,
            auth_type=AuthType.BEARER_TOKEN,
            description="Universal HTTP / REST API connector for SaaS and custom web endpoints.",
            connector_type=ConnectorArchitectureType.GENERIC_HTTP,
        ),
    )
    sftp = SftpConnector(allow_local=allow_private_ips)
    registry.register_connector(sftp, SftpConnector.default_catalog_summary())
    return registry


def create_empty_transformer_registry() -> TransformerRegistry:
    """Creates an empty domain-agnostic L3 TransformerRegistry."""
    return TransformerRegistry()


def create_empty_canonical_writer_registry() -> CanonicalWriterRegistry[CanonicalWriterPort]:
    """Creates an empty domain-agnostic L3 CanonicalWriterRegistry."""
    return CanonicalWriterRegistry()


def create_empty_workflow_definition_registry() -> InMemoryWorkflowDefinitionRegistry:
    """Creates an empty domain-agnostic L4 InMemoryWorkflowDefinitionRegistry."""
    return InMemoryWorkflowDefinitionRegistry()


def create_ip_control_plane_uow(
    global_session: AsyncSession,
) -> SqlAlchemyIpControlPlaneUnitOfWork:
    """Composition root factory assembling SqlAlchemyIpControlPlaneUnitOfWork with concrete repositories."""
    return SqlAlchemyIpControlPlaneUnitOfWork(
        global_session,
        connections=SqlAlchemyConnectionRepository(global_session),
        catalogs=SqlAlchemyCatalogRepository(global_session),
        stream_states=SqlAlchemyStreamStateRepository(global_session),
        sync_runs=SqlAlchemySyncRunRepository(global_session),
        transformations=SqlAlchemyTransformationRepository(global_session),
        stitches=SqlAlchemyStitchRepository(global_session),
    )


def create_ip_data_plane_uow(
    tenant_session: AsyncSession,
    storage: TieredStoragePort | None = None,
    *,
    domain_repository_factories: Mapping[str, DomainRepositoryFactory] | None = None,
) -> SqlAlchemyIpDataPlaneUnitOfWork:
    """Composition root factory assembling SqlAlchemyIpDataPlaneUnitOfWork with concrete repositories."""
    resolved_domain_repos = {
        name: factory(tenant_session)
        for name, factory in (domain_repository_factories or {}).items()
    }
    return SqlAlchemyIpDataPlaneUnitOfWork(
        tenant_session,
        inbound_records=SqlAlchemyInboundRecordRepository(tenant_session, storage=storage),
        replica_records=SqlAlchemyReplicaRecordRepository(tenant_session),
        replica_rejections=SqlAlchemyReplicaRejectionRepository(tenant_session),
        normalized_records=SqlAlchemyNormalizedRecordRepository(tenant_session),
        entity_maps=SqlAlchemyGlobalEntityMapRepository(tenant_session),
        outbound_records=SqlAlchemyOutboundRecordRepository(tenant_session, storage=storage),
        quarantine_records=SqlAlchemyQuarantineRecordRepository(tenant_session),
        normalization_ledger=SqlAlchemyNormalizationLedgerRepository(tenant_session),
        normalization_rejections=SqlAlchemyNormalizationRejectionRepository(tenant_session),
        pending_references=SqlAlchemyPendingReferenceRepository(tenant_session),
        traces=SqlAlchemyTraceRepository(
            tenant_session,
            event_spec=IP_TRACE_EVENT_SPEC,
            stage_specs=IP_TRACE_STAGE_SPECS,
        ),
        batch_manifests=SqlAlchemyBatchManifestRepository(tenant_session),
        domain_repositories=resolved_domain_repos,
    )


def create_ip_tenant_resolver(db_router: DatabaseRouterPort) -> SqlAlchemyIpTenantResolver:
    """Composition root factory assembling SqlAlchemyIpTenantResolver."""
    return SqlAlchemyIpTenantResolver(db_router=db_router)


def create_ip_tenant_uow_provider(
    resolver: IpTenantResolverPort,
    db_router: DatabaseRouterPort,
    storage: TieredStoragePort | None = None,
    *,
    domain_repository_factories: Mapping[str, DomainRepositoryFactory] | None = None,
) -> SqlAlchemyIpTenantUoWProvider:
    """Composition root factory assembling SqlAlchemyIpTenantUoWProvider."""
    return SqlAlchemyIpTenantUoWProvider(
        resolver=resolver,
        db_router=db_router,
        uow_factory=lambda session: create_ip_data_plane_uow(
            session,
            storage=storage,
            domain_repository_factories=domain_repository_factories,
        ),
    )


def create_ip_tiered_storage() -> TieredStoragePort:
    """Composition root factory assembling TieredStorageAdapter."""
    return TieredStorageAdapter()


def create_ip_columnar_batch_processor() -> ColumnarBatchProcessorPort:
    """Composition root factory assembling VectorizedIntervalBatchNormalizerAdapter."""
    return VectorizedIntervalBatchNormalizerAdapter()


def create_ip_interval_rollup_repository() -> IntervalRollupRepositoryPort:
    """Composition root factory assembling ColumnarIntervalRollupRepositoryAdapter."""
    return ColumnarIntervalRollupRepositoryAdapter()


def create_ip_inbound_verifier() -> InboundVerifierPort:
    """Composition root factory assembling default InboundVerifierPort."""
    return NoOpVerifier()


def create_ip_inbound_decoder() -> InboundPayloadDecoderPort:
    """Composition root factory assembling default InboundPayloadDecoderPort."""
    return StandardInboundPayloadDecoder()


def create_ip_inbound_ack() -> InboundAckPort:
    """Composition root factory assembling default InboundAckPort."""
    return StandardInboundAck()


def create_ip_token_refresh_lock(db_router: DatabaseRouterPort | None) -> TokenRefreshLockPort:
    """Composition root factory assembling SqlAlchemyTokenRefreshLockAdapter."""
    return SqlAlchemyTokenRefreshLockAdapter(db_router=db_router)


def create_ip_token_refresher(*, allow_private_ips: bool) -> OAuth2TokenRefresherPort:
    """Composition root factory assembling OAuth2StrategyTokenRefresher."""
    return OAuth2StrategyTokenRefresher(allow_private_ips=allow_private_ips)


def create_ip_workflow_uow(session: AsyncSession) -> WorkflowUnitOfWorkPort:
    """Composition root factory assembling SqlAlchemyWorkflowUnitOfWork with the IP outbox sink."""
    return create_workflow_uow(
        session,
        outbox_sink=lambda tid, et, ik, pl: stage_workflow_outbox_event(session, tid, et, ik, pl),
    )


def create_ip_stitch_dispatcher(
    *,
    db_router: DatabaseRouterPort,
    dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
    stitch_catalog: StitchCatalogRegistryPort,
    definition_registry: WorkflowDefinitionRegistryPort,
) -> IpStitchCanonicalDispatcherAdapter:
    """Composition root factory assembling IpStitchCanonicalDispatcherAdapter."""
    return IpStitchCanonicalDispatcherAdapter(
        db_router=db_router,
        dp_uow_provider=dp_uow_provider,
        stitch_catalog=stitch_catalog,
        definition_registry=definition_registry,
        workflow_uow_factory=create_ip_workflow_uow,
        control_plane_uow_factory=create_ip_control_plane_uow,
    )


def create_ip_stitch_worker_tick(
    *,
    db_router: DatabaseRouterPort,
    definition_registry: WorkflowDefinitionRegistryPort,
    handler_registry: StepHandlerRegistryPort,
) -> IpStitchWorkerTickExecutorPort:
    """Composition root factory assembling IpStitchWorkerTickAdapter."""
    return IpStitchWorkerTickAdapter(
        db_router=db_router,
        definition_registry=definition_registry,
        handler_registry=handler_registry,
        workflow_uow_factory=create_ip_workflow_uow,
    )


def create_ip_cp_outbox_components(
    *,
    db_router: DatabaseRouterPort,
    settings: IpEngineSettings,
    publisher: OutboxPublisherPort | None = None,
) -> tuple[OutboxRepositoryPort, OutboxCleanupRepositoryPort, OutboxPublisherPort]:
    """Composition root factory assembling IP Control Plane outbox repositories and publisher."""
    repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=db_router.global_session_scope,
        model_cls=IpOutboxRecord,
        source=IpOutboxSource.CONTROL_PLANE.value,
    )
    resolved_publisher = publisher or create_ip_cp_outbox_publisher(settings)
    return repo, repo, resolved_publisher


def create_ip_cp_outbox_relay(
    *,
    processor: OutboxProcessorUseCase,
    database_url: str,
    listen_channel: str,
    fallback_poll_interval: int,
) -> OutboxRelayPort:
    """Composition root factory assembling NotifyOutboxRelay for IP Control Plane."""
    return NotifyOutboxRelay(
        processor=processor,
        database_url=database_url,
        listen_channel=listen_channel,
        fallback_poll_interval=fallback_poll_interval,
        listener_connector=DatabaseProvider.connect_listener,
    )


def create_ip_dp_outbox_components(
    *,
    db_router: DatabaseRouterPort,
    settings: IpEngineSettings,
    publisher: OutboxPublisherPort | None = None,
) -> tuple[
    ShardOutboxDrainPort,
    OutboxRepositoryPort,
    OutboxCleanupRepositoryPort,
    TraceRetentionRepositoryPort,
    OutboxPublisherPort,
]:
    """Composition root factory assembling IP Data Plane sharded outbox and retention components."""
    dp_repo = SqlAlchemyShardedOutboxRepository(
        db_router,
        model_cls=IpDataPlaneOutboxRecord,
        app_slug="ip",
        source=IpOutboxSource.DATA_PLANE.value,
    )
    retention_repo = SqlAlchemyShardedTraceRetentionRepository(
        db_router,
        app_slug="ip",
        trace_event_model_cls=IpTraceEventModel,
        processed_event_model_cls=IpProcessedEventModel,
    )
    resolved_publisher = publisher or create_ip_dp_outbox_publisher(settings)
    return dp_repo, dp_repo, dp_repo, retention_repo, resolved_publisher


def create_ip_dp_outbox_relay(
    *,
    repository: ShardOutboxDrainPort,
    publisher: OutboxPublisherPort,
    batch_size: int,
    lock_lease_ms: int,
) -> OutboxRelayPort:
    """Composition root factory assembling MultiShardOutboxDrainRelay for IP Data Plane."""
    return MultiShardOutboxDrainRelay(
        repository=repository,
        publisher=publisher,
        batch_size=batch_size,
        lock_lease_ms=lock_lease_ms,
    )


class SessionScopedOutboundDeliveryExecutor(IpOutboundDeliveryExecutorPort):
    """Opens an isolated Control Plane GlobalSession per outbound delivery execution."""

    def __init__(
        self,
        *,
        db_router: DatabaseRouterPort,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        connectors: Mapping[str, DestinationConnectorPort],
        tiered_storage: TieredStoragePort,
        cipher: CipherPort,
        token_refresher: OAuth2TokenRefresherPort,
        lock_port: TokenRefreshLockPort,
        max_delivery_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
        max_causation_depth: int = DEFAULT_MAX_CAUSATION_DEPTH,
    ) -> None:
        self._db_router = db_router
        self._dp_uow_provider = dp_uow_provider
        self._connectors = connectors
        self._tiered_storage = tiered_storage
        self._cipher = cipher
        self._token_refresher = token_refresher
        self._lock_port = lock_port
        self._max_delivery_attempts = max_delivery_attempts
        self._max_causation_depth = max_causation_depth

    async def execute(
        self,
        command: DeliverOutboundRecordCommand,
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        async with self._db_router.global_session_scope() as global_session:
            cp_uow = create_ip_control_plane_uow(global_session)
            token_mgr = TokenManagerService(
                control_plane_uow=cp_uow,
                cipher=self._cipher,
                token_refresher=self._token_refresher,
                lock_port=self._lock_port,
            )
            use_case = DeliverOutboundRecordUseCase(
                data_plane_uow_provider=self._dp_uow_provider,
                connectors=self._connectors,
                tiered_storage=self._tiered_storage,
                token_manager=token_mgr,
                max_delivery_attempts=self._max_delivery_attempts,
                max_causation_depth=self._max_causation_depth,
            )
            return await use_case.execute(command)


class SessionScopedOutboundDeliveryStager(OutboundDeliveryStagerPort):
    """Opens an isolated Control Plane GlobalSession per pure L4->L5 egress outbox staging call."""

    def __init__(
        self,
        *,
        db_router: DatabaseRouterPort,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        tiered_storage: TieredStoragePort,
    ) -> None:
        self._db_router = db_router
        self._dp_uow_provider = dp_uow_provider
        self._tiered_storage = tiered_storage

    async def execute(
        self,
        command: StageOutboundDeliveryCommand,
    ) -> Result[StageOutboundDeliveryResponse, IpError]:
        async with self._db_router.global_session_scope() as global_session:
            cp_uow = create_ip_control_plane_uow(global_session)
            use_case = StageOutboundDeliveryUseCase(
                control_plane_uow=cp_uow,
                data_plane_uow_provider=self._dp_uow_provider,
                tiered_storage=self._tiered_storage,
            )
            return await use_case.execute(command)


def create_default_stitch_catalog() -> InMemoryStitchCatalogRegistry:
    """Creates an empty domain-agnostic InMemoryStitchCatalogRegistry."""
    return InMemoryStitchCatalogRegistry()


def create_default_step_handler_registry(
    *,
    uow_provider: IpDataPlaneUnitOfWorkProviderPort,
    delivery_stager: OutboundDeliveryStagerPort,
    outbound_lookup: OutboundRecordLookupPort,
) -> InMemoryStepHandlerRegistry:
    """Creates and populates an InMemoryStepHandlerRegistry with all 3 built-in IP Stitch step handlers."""
    registry = InMemoryStepHandlerRegistry()
    registry.register(
        QueryReplicaStepHandler(replica_lookup=TenantAwareReplicaLookupAdapter(uow_provider))
    )
    registry.register(
        EmitNotificationStepHandler(outbox=TenantAwareNotificationOutboxAdapter(uow_provider))
    )
    registry.register(
        ExecuteHttpActionStepHandler(
            delivery_stager=delivery_stager,
            outbound_lookup=outbound_lookup,
        )
    )
    return registry


def create_default_stage_replay_processors() -> dict[PipelineStage, StageReplayProcessorPort]:
    """Composition root factory assembling all per-stage StageReplayProcessorPort strategies."""
    processors: tuple[StageReplayProcessorPort, ...] = (
        IngestStageReplayProcessor(),
        NormalizeStageReplayProcessor(),
        StitchStageReplayProcessor(),
        DeliverStageReplayProcessor(),
    )
    return {processor.stage: processor for processor in processors}


class Container(containers.DeclarativeContainer):
    """Declarative IoC container for the Integration Platform Engine."""

    config = providers.Configuration(
        default={
            "allow_private_ips": False,
            "max_delivery_attempts": DEFAULT_MAX_DELIVERY_ATTEMPTS,
            "max_causation_depth": DEFAULT_MAX_CAUSATION_DEPTH,
        }
    )

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    cipher = providers.Singleton(SecurityProvider.get_cipher)
    auth_resolver = providers.Singleton(AuthStrategyResolver)

    catalog_registry = providers.Factory(
        create_engine_catalog_registry,
        allow_private_ips=config.allow_private_ips.as_(bool),
        auth_resolver=auth_resolver,
    )
    connector_mapping: providers.Factory[Mapping[str, ConnectorPort]] = providers.Factory(
        CatalogConnectorMapping,
        registry=catalog_registry,
    )

    extractor_registry = providers.Singleton(RecordExtractorRegistry)

    payload_storage = providers.Singleton(
        StorageProvider.create_payload_storage,
        bucket=DEFAULT_IP_PAYLOAD_BUCKET,
    )

    tiered_storage = providers.Singleton(
        TieredStorageAdapter,
        storage_client=payload_storage,
    )

    # -----------------------------------------------------------------------
    # Repositories and Units of Work
    # -----------------------------------------------------------------------
    db_router: providers.Dependency[DatabaseRouterPort] = providers.Dependency()
    tenant_resolver: providers.Dependency[IpTenantResolverPort] = providers.Dependency()
    domain_repository_factories: providers.Object[Mapping[str, DomainRepositoryFactory]] = (
        providers.Object({})
    )
    cp_uow = providers.Factory(create_ip_control_plane_uow)
    dp_uow = providers.Factory(
        create_ip_data_plane_uow,
        storage=tiered_storage,
        domain_repository_factories=domain_repository_factories,
    )
    dp_uow_provider = providers.Factory(
        create_ip_tenant_uow_provider,
        resolver=tenant_resolver,
        db_router=db_router,
        storage=tiered_storage,
        domain_repository_factories=domain_repository_factories,
    )

    # -----------------------------------------------------------------------
    # Replication Use Cases (Layer 2)
    # -----------------------------------------------------------------------
    replicate_records_use_case = providers.Factory(
        ReplicateRecordsUseCase,
        extractor_registry=extractor_registry,
        tiered_storage=tiered_storage,
    )
    sweep_stale_replicas_use_case = providers.Factory(SweepStaleReplicasUseCase)

    # -----------------------------------------------------------------------
    # Normalization Registries & Use Cases (Layer 3)
    # -----------------------------------------------------------------------
    transformer_registry = providers.Singleton(create_empty_transformer_registry)
    writer_registry: providers.Singleton[CanonicalWriterRegistry[CanonicalWriterPort]] = (
        providers.Singleton(create_empty_canonical_writer_registry)
    )
    entity_registry = providers.Singleton(CanonicalEntityRegistry)
    normalization_error_policy = providers.Singleton(DefaultNormalizationErrorPolicy)

    bind_stream_transformation_use_case = providers.Factory(
        BindStreamTransformationUseCase,
        control_plane_uow=cp_uow,
        transformer_registry=transformer_registry,
    )
    promote_transformation_version_use_case = providers.Factory(
        PromoteTransformationVersionUseCase,
        control_plane_uow=cp_uow,
    )
    normalize_replica_record_use_case = providers.Factory(
        NormalizeReplicaRecordUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        transformer_registry=transformer_registry,
        writer_registry=writer_registry,
        entity_registry=entity_registry,
        error_policy=normalization_error_policy,
    )
    process_inbound_range_use_case = providers.Factory(
        ProcessInboundRangeUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_replica_record_use_case,
        extractor_registry=extractor_registry,
        tiered_storage=tiered_storage,
    )
    backfill_stream_normalization_use_case = providers.Factory(
        BackfillStreamNormalizationUseCase,
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_replica_record_use_case,
    )

    # -----------------------------------------------------------------------
    # OAuth2 Token Refresh Manager & Ingestion/Delivery (Layer 0, Layer 1, Layer 5)
    # -----------------------------------------------------------------------
    token_refresh_lock = providers.Singleton(
        SqlAlchemyTokenRefreshLockAdapter,
        db_router=db_router,
    )
    oauth2_token_refresher = providers.Factory(
        OAuth2StrategyTokenRefresher,
        allow_private_ips=config.allow_private_ips.as_(bool),
    )
    token_manager = providers.Factory(
        TokenManagerService,
        control_plane_uow=cp_uow,
        cipher=cipher,
        token_refresher=oauth2_token_refresher,
        lock_port=token_refresh_lock,
    )
    discover_catalog_use_case = providers.Factory(
        DiscoverCatalogUseCase,
        uow=cp_uow,
        cipher=cipher,
        connectors=connector_mapping,
        token_manager=token_manager,
    )
    fetch_record_use_case = providers.Factory(
        FetchRecordUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        tiered_storage=tiered_storage,
        cipher=cipher,
        connectors=connector_mapping,
        token_manager=token_manager,
    )
    run_sync_use_case = providers.Factory(
        RunSyncUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        tiered_storage=tiered_storage,
        cipher=cipher,
        connectors=connector_mapping,
        token_manager=token_manager,
    )
    deliver_outbound_record_use_case = providers.Factory(
        DeliverOutboundRecordUseCase,
        data_plane_uow_provider=dp_uow_provider,
        connectors=connector_mapping,
        tiered_storage=tiered_storage,
        token_manager=token_manager,
    )
    outbound_record_lookup = providers.Factory(
        TenantAwareOutboundRecordLookupAdapter,
        uow_provider=dp_uow_provider,
    )
    session_scoped_outbound_delivery = providers.Factory(
        SessionScopedOutboundDeliveryExecutor,
        db_router=db_router,
        dp_uow_provider=dp_uow_provider,
        connectors=connector_mapping,
        tiered_storage=tiered_storage,
        cipher=cipher,
        token_refresher=oauth2_token_refresher,
        lock_port=token_refresh_lock,
        max_delivery_attempts=config.max_delivery_attempts.as_(int),
        max_causation_depth=config.max_causation_depth.as_(int),
    )
    session_scoped_outbound_delivery_stager = providers.Factory(
        SessionScopedOutboundDeliveryStager,
        db_router=db_router,
        dp_uow_provider=dp_uow_provider,
        tiered_storage=tiered_storage,
    )
    stage_outbound_delivery_use_case = providers.Factory(
        StageOutboundDeliveryUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        tiered_storage=tiered_storage,
    )
    execute_http_action_step_handler = providers.Factory(
        ExecuteHttpActionStepHandler,
        delivery_stager=session_scoped_outbound_delivery_stager,
        outbound_lookup=outbound_record_lookup,
    )

    # -----------------------------------------------------------------------
    # Stitch / Durable Workflow Registries (Layer 4)
    # -----------------------------------------------------------------------
    stitch_catalog = providers.Singleton(create_default_stitch_catalog)
    workflow_definition_registry = providers.Singleton(create_empty_workflow_definition_registry)
    step_handler_registry = providers.Singleton(
        create_default_step_handler_registry,
        uow_provider=dp_uow_provider,
        delivery_stager=session_scoped_outbound_delivery_stager,
        outbound_lookup=outbound_record_lookup,
    )
    predicate_registry = providers.Singleton(InMemoryPredicateRegistry)

    # -----------------------------------------------------------------------
    # Support Timeline, Trace Lineage & Deterministic Replay (Phase 9)
    # -----------------------------------------------------------------------
    stage_replay_processors = providers.Singleton(create_default_stage_replay_processors)
    get_ip_trace_use_case = providers.Factory(
        GetIpTraceUseCase,
        uow_provider=dp_uow_provider,
    )
    get_ip_trace_lineage_use_case = providers.Factory(
        GetIpTraceLineageUseCase,
        uow_provider=dp_uow_provider,
    )
    replay_stage_use_case = providers.Factory(
        ReplayStageUseCase,
        uow_provider=dp_uow_provider,
        stage_processors=stage_replay_processors,
    )
    modify_and_replay_use_case = providers.Factory(
        ModifyAndReplayUseCase,
        uow_provider=dp_uow_provider,
        stage_processors=stage_replay_processors,
    )
    bulk_replay_stage_use_case = providers.Factory(
        BulkReplayStageUseCase,
        uow_provider=dp_uow_provider,
        stage_processors=stage_replay_processors,
    )

    # -----------------------------------------------------------------------
    # High-Frequency Columnar Interval Streams Engine
    # -----------------------------------------------------------------------
    columnar_batch_processor = providers.Singleton(create_ip_columnar_batch_processor)
    interval_rollup_repository = providers.Singleton(create_ip_interval_rollup_repository)

    buffer_raw_interval_batch_use_case = providers.Factory(
        BufferRawIntervalBatchUseCase,
        cp_uow=cp_uow,
        dp_uow_provider=dp_uow_provider,
        storage=tiered_storage,
    )
    process_interval_batch_use_case = providers.Factory(
        ProcessIntervalBatchUseCase,
        dp_uow_provider=dp_uow_provider,
        storage=tiered_storage,
        columnar_processor=columnar_batch_processor,
        rollup_repository=interval_rollup_repository,
    )
    get_batch_reconciliation_summary_use_case = providers.Factory(
        GetBatchReconciliationSummaryUseCase,
        dp_uow_provider=dp_uow_provider,
    )
    get_daily_completeness_use_case = providers.Factory(
        GetDailyCompletenessUseCase,
        rollup_repository=interval_rollup_repository,
    )
    get_daily_tou_rollups_use_case = providers.Factory(
        GetDailyTouRollupsUseCase,
        rollup_repository=interval_rollup_repository,
    )
    trace_interval_lineage_use_case = providers.Factory(
        TraceIntervalLineageUseCase,
        dp_uow_provider=dp_uow_provider,
        rollup_repository=interval_rollup_repository,
    )
    record_settlement_receipt_use_case = providers.Factory(
        RecordSettlementReceiptUseCase,
        dp_uow_provider=dp_uow_provider,
        rollup_repository=interval_rollup_repository,
    )


__all__ = [
    "Container",
    "DomainRepositoryFactory",
    "SessionScopedOutboundDeliveryExecutor",
    "SessionScopedOutboundDeliveryStager",
    "create_default_stage_replay_processors",
    "create_default_stitch_catalog",
    "create_empty_canonical_writer_registry",
    "create_empty_transformer_registry",
    "create_empty_workflow_definition_registry",
    "create_engine_catalog_registry",
    "create_ip_columnar_batch_processor",
    "create_ip_control_plane_uow",
    "create_ip_cp_outbox_components",
    "create_ip_cp_outbox_relay",
    "create_ip_data_plane_uow",
    "create_ip_dp_outbox_components",
    "create_ip_dp_outbox_relay",
    "create_ip_inbound_ack",
    "create_ip_inbound_decoder",
    "create_ip_inbound_verifier",
    "create_ip_interval_rollup_repository",
    "create_ip_stitch_dispatcher",
    "create_ip_stitch_worker_tick",
    "create_ip_tenant_resolver",
    "create_ip_tenant_uow_provider",
    "create_ip_tiered_storage",
    "create_ip_token_refresh_lock",
    "create_ip_token_refresher",
    "create_ip_workflow_uow",
]
