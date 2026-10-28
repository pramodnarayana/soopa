"""Declarative IoC Container for the Integration Platform (IP) Engine."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping

from database.router import DatabaseRouterPort
from dependency_injector import containers, providers
from orchestration.adapters.outbound.database.uow import SqlAlchemyWorkflowUnitOfWork
from orchestration.application.services.registries import (
    InMemoryPredicateRegistry,
    InMemoryStepHandlerRegistry,
)
from orchestration.ports.outbound import WorkflowUnitOfWorkPort
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider
from sqlalchemy.ext.asyncio import AsyncSession
from storage.provider import StorageProvider

from ip.application.domains.energy.ports import EnergyDomainRepositoryPort
from ip.application.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.application.domains.energy.writers import (
    create_default_canonical_writer_registry,
)
from ip.application.stitches.registry_loader import (
    create_default_workflow_definition_registry,
    register_default_stitches,
)
from ip.application.transformers.registry_loader import create_default_transformer_registry
from ip.engine.adapters.outbound.auth.oauth2_strategy import (
    OAuth2StrategyTokenRefresher,
)
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    SqlAlchemyTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.connectors.catalog_registry import (
    ConnectorCatalogRegistry,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
    stage_workflow_outbox_event,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.adapters.outbound.stitches.step_handlers import (
    EmitNotificationStepHandler,
    ExecuteHttpActionStepHandler,
    OutboundDeliveryExecutorPort,
    OutboundRecordLookupPort,
    QueryReplicaStepHandler,
    TenantAwareNotificationOutboxAdapter,
    TenantAwareOutboundRecordLookupAdapter,
    TenantAwareReplicaLookupAdapter,
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
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordUseCase,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncUseCase,
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
from ip.engine.application.use_cases.normalization.promote_transformation_version_use_case import (
    PromoteTransformationVersionUseCase,
)
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicateRecordsUseCase,
)
from ip.engine.application.use_cases.replication.sweep_stale_replicas_use_case import (
    SweepStaleReplicasUseCase,
)
from ip.engine.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_lineage_use_case import (
    GetIpTraceLineageUseCase,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_use_case import (
    GetIpTraceUseCase,
)
from ip.engine.application.use_cases.transactions.modify_and_replay_use_case import (
    ModifyAndReplayTransactionUseCase,
)
from ip.engine.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.services.canonical_entity_registry import CanonicalEntityRegistry
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.domain.services.default_normalization_error_policy import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.connector_port import DestinationConnectorPort
from ip.engine.ports.outbound.record_extractor_port import RecordExtractorRegistry
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    TokenRefreshLockPort,
)
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)


class SessionScopedOutboundDeliveryExecutor(OutboundDeliveryExecutorPort):
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
    ) -> None:
        self._db_router = db_router
        self._dp_uow_provider = dp_uow_provider
        self._connectors = connectors
        self._tiered_storage = tiered_storage
        self._cipher = cipher
        self._token_refresher = token_refresher
        self._lock_port = lock_port

    async def execute(
        self,
        command: DeliverOutboundRecordCommand,
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for global_session in session_gen:
                cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
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
                )
                return await use_case.execute(command)
        raise RuntimeError("DatabaseRouter did not yield a GlobalSession.")


def _resolve_energy_domain_repo(
    uow: IpDataPlaneUnitOfWorkPort,
) -> EnergyDomainRepositoryPort | None:
    """Composition root adapter factory binding SqlAlchemyEnergyDomainRepository to the Data Plane session."""
    if isinstance(uow, SqlAlchemyIpDataPlaneUnitOfWork):
        return SqlAlchemyEnergyDomainRepository(uow.tenant_session)
    return None


def create_default_stitch_catalog() -> InMemoryStitchCatalogRegistry:
    """Creates and populates an InMemoryStitchCatalogRegistry with built-in stitches."""
    registry = InMemoryStitchCatalogRegistry()
    register_default_stitches(registry)
    return registry


def create_ip_workflow_uow(session: AsyncSession) -> WorkflowUnitOfWorkPort:
    """Composition root factory assembling SqlAlchemyWorkflowUnitOfWork with the IP outbox sink."""
    return SqlAlchemyWorkflowUnitOfWork(
        session,
        outbox_sink=lambda tid, et, ik, pl: stage_workflow_outbox_event(session, tid, et, ik, pl),
    )


def create_default_step_handler_registry(
    *,
    uow_provider: IpDataPlaneUnitOfWorkProviderPort,
    delivery_executor: OutboundDeliveryExecutorPort,
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
            delivery_executor=delivery_executor,
            outbound_lookup=outbound_lookup,
        )
    )
    return registry


class Container(containers.DeclarativeContainer):
    """Declarative IoC container for the Integration Platform Engine."""

    config = providers.Configuration()

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    cipher = providers.Singleton(SecurityProvider.get_cipher)

    catalog_registry = providers.Factory(
        ConnectorCatalogRegistry,
        allow_private_ips=config.allow_private_ips.as_(bool),
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
    tenant_resolver = providers.Dependency(instance_of=IpTenantResolver)
    cp_uow = providers.Factory(SqlAlchemyIpControlPlaneUnitOfWork)
    dp_uow = providers.Factory(
        SqlAlchemyIpDataPlaneUnitOfWork,
        storage=tiered_storage,
    )
    dp_uow_provider = providers.Factory(
        IpTenantUoWProvider,
        resolver=tenant_resolver,
        db_router=db_router,
        storage=tiered_storage,
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
    transformer_registry = providers.Singleton(create_default_transformer_registry)
    writer_registry: providers.Singleton[InMemoryCanonicalWriterRegistry[CanonicalWriterPort]] = (
        providers.Singleton(
            create_default_canonical_writer_registry,
            repo_factory=_resolve_energy_domain_repo,
        )
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
        connectors=catalog_registry,
        token_manager=token_manager,
    )
    fetch_record_use_case = providers.Factory(
        FetchRecordUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        tiered_storage=tiered_storage,
        cipher=cipher,
        connectors=catalog_registry,
        token_manager=token_manager,
    )
    run_sync_use_case = providers.Factory(
        RunSyncUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        tiered_storage=tiered_storage,
        cipher=cipher,
        connectors=catalog_registry,
        token_manager=token_manager,
    )
    deliver_outbound_record_use_case = providers.Factory(
        DeliverOutboundRecordUseCase,
        data_plane_uow_provider=dp_uow_provider,
        connectors=catalog_registry,
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
        connectors=catalog_registry,
        tiered_storage=tiered_storage,
        cipher=cipher,
        token_refresher=oauth2_token_refresher,
        lock_port=token_refresh_lock,
    )
    execute_http_action_step_handler = providers.Factory(
        ExecuteHttpActionStepHandler,
        delivery_executor=session_scoped_outbound_delivery,
        outbound_lookup=outbound_record_lookup,
    )

    # -----------------------------------------------------------------------
    # Stitch / Durable Workflow Registries (Layer 4)
    # -----------------------------------------------------------------------
    stitch_catalog = providers.Singleton(create_default_stitch_catalog)
    workflow_definition_registry = providers.Singleton(create_default_workflow_definition_registry)
    step_handler_registry = providers.Singleton(
        create_default_step_handler_registry,
        uow_provider=dp_uow_provider,
        delivery_executor=session_scoped_outbound_delivery,
        outbound_lookup=outbound_record_lookup,
    )
    predicate_registry = providers.Singleton(InMemoryPredicateRegistry)

    # -----------------------------------------------------------------------
    # Support Timeline, Trace Lineage & Deterministic Replay (Phase 9)
    # -----------------------------------------------------------------------
    get_ip_trace_use_case = providers.Factory(
        GetIpTraceUseCase,
        uow_provider=dp_uow_provider,
    )
    get_ip_trace_lineage_use_case = providers.Factory(
        GetIpTraceLineageUseCase,
        uow_provider=dp_uow_provider,
    )
    replay_transaction_use_case = providers.Factory(
        ReplayTransactionUseCase,
        uow_provider=dp_uow_provider,
    )
    modify_and_replay_use_case = providers.Factory(
        ModifyAndReplayTransactionUseCase,
        uow_provider=dp_uow_provider,
    )
    bulk_replay_transactions_use_case = providers.Factory(
        BulkReplayTransactionsUseCase,
        uow_provider=dp_uow_provider,
    )


__all__ = ["Container", "create_default_stitch_catalog", "create_ip_workflow_uow"]
