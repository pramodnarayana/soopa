"""Declarative IoC Container for the Integration Platform (IP) bounded context."""

from __future__ import annotations

from database.router import DatabaseRouterPort
from dependency_injector import containers, providers
from security.provider import SecurityProvider
from storage.provider import StorageProvider

from ip.engine.adapters.outbound.auth.oauth2_strategy import (
    OAuth2StrategyTokenRefresher,
)
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    InMemoryTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.connectors.catalog_registry import (
    ConnectorCatalogRegistry,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.adapters.outbound.stitches.step_handlers import (
    ExecuteHttpActionStepHandler,
    TenantAwareOutboundRecordLookupAdapter,
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
from ip.engine.application.use_cases.normalization.bind_stream_mapping_use_case import (
    BindStreamMappingUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.normalization.promote_mapping_version_use_case import (
    PromoteMappingVersionUseCase,
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
from ip.engine.domain.services.canonical_entity_registry import CanonicalEntityRegistry
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.domain.services.default_normalization_error_policy import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.services.mapper_registry import InMemoryMapperRegistry
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.record_extractor_port import RecordExtractorRegistry


class Container(containers.DeclarativeContainer):
    """Declarative IoC container for the Integration Platform bounded context."""

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
    mapper_registry = providers.Singleton(InMemoryMapperRegistry)
    writer_registry: providers.Singleton[InMemoryCanonicalWriterRegistry[CanonicalWriterPort]] = (
        providers.Singleton(InMemoryCanonicalWriterRegistry)
    )
    entity_registry = providers.Singleton(CanonicalEntityRegistry)
    normalization_error_policy = providers.Singleton(DefaultNormalizationErrorPolicy)

    bind_stream_mapping_use_case = providers.Factory(
        BindStreamMappingUseCase,
        control_plane_uow=cp_uow,
        mapper_registry=mapper_registry,
    )
    promote_mapping_version_use_case = providers.Factory(
        PromoteMappingVersionUseCase,
        control_plane_uow=cp_uow,
    )
    normalize_replica_record_use_case = providers.Factory(
        NormalizeReplicaRecordUseCase,
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        mapper_registry=mapper_registry,
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
    token_refresh_lock = providers.Singleton(InMemoryTokenRefreshLockAdapter)
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
    execute_http_action_step_handler = providers.Factory(
        ExecuteHttpActionStepHandler,
        delivery_executor=deliver_outbound_record_use_case,
        outbound_lookup=outbound_record_lookup,
    )

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


__all__ = ["Container"]
