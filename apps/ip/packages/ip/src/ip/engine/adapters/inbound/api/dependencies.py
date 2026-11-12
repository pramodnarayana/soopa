"""FastAPI dependencies and perimeter tenant guard for Integration Platform API routers."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from typing import Annotated

import structlog
from database.provider import DatabaseProvider
from database.router import DatabaseRouterPort
from fastapi import Depends, HTTPException, Path, Request, status
from identity.domain.identity_context import IdentityContext
from ip.engine.application.api_provider_port import IpApiProviderPort
from ip.engine.application.use_cases.connections.connection_entity_use_cases import (
    AddConnectionEntityUseCase,
    ListConnectionEntitiesUseCase,
    RemoveConnectionEntityUseCase,
    ResetConnectionEntityCheckpointUseCase,
    UpdateConnectionEntityUseCase,
)
from ip.engine.application.use_cases.connections.discover_catalog_use_case import (
    DiscoverCatalogUseCase,
)
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.application.use_cases.ingestion.ingest_connection_webhook_use_case import (
    IngestConnectionWebhookUseCase,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushExecutorFactory,
    ReceivePushExecutorPort,
    ReceivePushUseCase,
)
from ip.engine.application.use_cases.ingestion.sync_run_control_plane_use_cases import (
    GetSyncRunUseCase,
    ListSyncRunsUseCase,
    TriggerSyncRunUseCase,
)
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.domain.authorization import IpPermission, has_ip_permission
from ip.engine.domain.enums import PipelineStage
from ip.engine.ports.outbound.catalog_registry_port import (
    CatalogConnectorMapping,
    CatalogRegistryPort,
)
from ip.engine.ports.outbound.columnar_batch_processor_port import ColumnarBatchProcessorPort
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.interval_rollup_repository_port import IntervalRollupRepositoryPort
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
    StitchShardGatewayPort,
)
from ip.engine.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    TokenRefreshLockPort,
)
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
    IpTenantResolverPort,
)
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from security.ports.cipher_port import CipherPort
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _get_api_provider(request: Request) -> IpApiProviderPort[AsyncSession, DatabaseRouterPort]:
    try:
        provider: IpApiProviderPort[AsyncSession, DatabaseRouterPort] | None = (
            request.app.state.ip_api_provider
        )
    except AttributeError:
        provider = None
    if provider is None:
        raise RuntimeError(
            "IpApiProviderPort is not initialized on app.state.ip_api_provider. "
            "Register routes via IpApiModule.register_routes(app) first."
        )
    return provider


async def get_ip_global_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """Yields a request-scoped Control Plane GlobalSession from the host shell's DatabaseProvider."""
    db_provider: DatabaseProvider = request.app.state.db_provider
    async with db_provider.session() as session:
        yield session


def get_ip_control_plane_uow(
    request: Request,
    global_session: Annotated[AsyncSession, Depends(get_ip_global_session)],
) -> IpControlPlaneUnitOfWorkPort:
    """Resolves an IpControlPlaneUnitOfWorkPort bound to the request Control Plane session."""
    return _get_api_provider(request).create_control_plane_uow(global_session)


def get_tenant_repository(
    request: Request,
) -> TenantRepositoryPort:
    """Resolves a short-lived session-scoped TenantRepositoryPort from the host DatabaseProvider."""
    db_provider: DatabaseProvider = request.app.state.db_provider
    return _get_api_provider(request).create_scoped_tenant_repository(db_provider.session)


def get_ip_data_plane_uow_provider(request: Request) -> IpDataPlaneUnitOfWorkProviderPort:
    """Resolves the IpDataPlaneUnitOfWorkProviderPort bound to the centralized DatabaseRouter and IpTenantResolverPort."""
    provider = _get_api_provider(request)
    state = request.app.state
    db_router: DatabaseRouterPort = state.db_router
    try:
        resolver: IpTenantResolverPort | None = state.ip_tenant_resolver
    except AttributeError:
        resolver = None
    try:
        storage: TieredStoragePort | None = state.ip_tiered_storage
    except AttributeError:
        storage = None

    uow_provider, resolved_resolver, resolved_storage = provider.resolve_data_plane_uow_provider(
        db_router=db_router,
        resolver=resolver,
        storage=storage,
    )
    state.ip_tenant_resolver = resolved_resolver
    state.ip_tiered_storage = resolved_storage
    return uow_provider


async def require_tenant_member(
    request: Request,
    tenant_repo: Annotated[TenantRepositoryPort, Depends(get_tenant_repository)],
    tenant_id: Annotated[str, Path(...)],
) -> IdentityContext:
    """Enforces authenticated tenant membership for tenant-scoped IP routes."""
    try:
        identity: IdentityContext | None = request.state.identity
    except AttributeError:
        identity = None
    if identity is None:
        logger.error("ip_tenant_authentication_missing", requested_tenant_id=tenant_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TENANT_GUARD_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if identity.is_platform_admin:
        tenant_summary = await tenant_repo.get_by_idp_tenant_id(tenant_id)
        canonical_tenant_id = tenant_summary.id if tenant_summary is not None else tenant_id
        request.state.identity = identity
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    if tenant_id in identity.authorized_tenants or identity.tenant_id == tenant_id:
        canonical_tenant_id = str(identity.tenant_mapping.get(tenant_id, tenant_id))
        request.state.identity = identity
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    logger.error(
        "ip_tenant_authorization_failed",
        requested_tenant_id=tenant_id,
        context_tenant_id=identity.tenant_id,
        authorized_tenants=sorted(identity.authorized_tenants),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"User does not belong to tenant {tenant_id}.",
    )


def get_effective_ucp_tenant_id(
    request: Request,
    tenant_id: Annotated[str, Path(...)],
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
) -> str:
    """Returns the canonical UCP tenant ID resolved by the perimeter tenant guard."""
    try:
        resolved: str | None = request.state.ucp_tenant_id
    except AttributeError:
        resolved = None
    if isinstance(resolved, str) and resolved.strip():
        return resolved.strip()
    return tenant_id


async def resolve_tenant_id_by_slug(
    request: Request,
    tenant_repo: Annotated[TenantRepositoryPort, Depends(get_tenant_repository)],
    tenant_slug: Annotated[str, Path(...)],
) -> str:
    """Resolves `{tenant_slug}` to canonical `tenant_id` for slug-addressed ingress routes."""
    tenant_summary = await tenant_repo.get_by_slug(tenant_slug)
    resolved_id = tenant_summary.id if tenant_summary is not None else None

    try:
        identity: IdentityContext | None = request.state.identity
    except AttributeError:
        identity = None

    if (
        identity is not None
        and not identity.is_platform_admin
        and (
            resolved_id is None
            or (
                resolved_id not in identity.authorized_tenants and identity.tenant_id != resolved_id
            )
        )
    ):
        logger.error(
            "ip_tenant_slug_authorization_failed",
            requested_tenant_slug=tenant_slug,
            context_tenant_id=identity.tenant_id,
            authorized_tenants=sorted(identity.authorized_tenants),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User does not belong to tenant '{tenant_slug}'.",
        )

    if resolved_id is None:
        logger.error("ip_tenant_slug_not_found", requested_tenant_slug=tenant_slug)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_slug}' was not found.",
        )

    canonical_tenant_id = (
        str(identity.tenant_mapping.get(resolved_id, resolved_id))
        if identity is not None
        else resolved_id
    )
    request.state.ucp_tenant_id = canonical_tenant_id
    return canonical_tenant_id


def require_ip_permission(
    permission: IpPermission,
) -> Callable[[IdentityContext, str], Awaitable[IdentityContext]]:
    """FastAPI dependency factory enforcing a specific discrete IP resource permission."""

    async def _dependency(
        identity: Annotated[IdentityContext, Depends(require_tenant_member)],
        tenant_id: str,
    ) -> IdentityContext:
        if not has_ip_permission(identity, permission, tenant_id=tenant_id):
            logger.error(
                "ip_permission_denied",
                subject=identity.subject,
                tenant_id=tenant_id,
                required_permission=permission.value,
                roles=list(identity.roles),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"FORBIDDEN: Missing required permission '{permission.value}'.",
            )
        return identity

    return _dependency


require_raw_records_read = require_ip_permission(IpPermission.IP_RECORDS_RAW_READ)
require_canonical_records_read = require_ip_permission(IpPermission.IP_RECORDS_CANONICAL_READ)
require_flows_read = require_ip_permission(IpPermission.IP_FLOWS_READ)
require_flows_write = require_ip_permission(IpPermission.IP_FLOWS_WRITE)
require_sync_trigger = require_ip_permission(IpPermission.IP_SYNC_TRIGGER)


def get_catalog_registry(request: Request) -> CatalogRegistryPort:
    """Resolves a CatalogRegistryPort configured according to IP engine settings."""
    return _get_api_provider(request).get_catalog_registry()


def get_connectors(
    registry: Annotated[CatalogRegistryPort, Depends(get_catalog_registry)],
) -> Mapping[str, ConnectorPort]:
    """Resolves a Mapping[str, ConnectorPort] backed by CatalogRegistryPort."""
    return CatalogConnectorMapping(registry)


def get_cipher(request: Request) -> CipherPort:
    """Resolves the platform CipherPort."""
    return _get_api_provider(request).get_cipher()


def get_tiered_storage(request: Request) -> TieredStoragePort:
    """Resolves the TieredStoragePort backed by platform S3 PayloadStoragePort."""
    return _get_api_provider(request).get_tiered_storage()


def get_inbound_verifier(request: Request) -> InboundVerifierPort:
    """Resolves the InboundVerifierPort for L1 push webhook verification."""
    return _get_api_provider(request).get_inbound_verifier()


def get_inbound_decoder(request: Request) -> InboundPayloadDecoderPort:
    """Resolves the InboundPayloadDecoderPort for L1 push webhook payload decoding."""
    return _get_api_provider(request).get_inbound_decoder()


def get_inbound_ack(request: Request) -> InboundAckPort:
    """Resolves the InboundAckPort for L1 push webhook acknowledgments."""
    return _get_api_provider(request).get_inbound_ack()


def get_token_refresh_lock(request: Request) -> TokenRefreshLockPort:
    """Resolves the TokenRefreshLockPort from application state."""
    state = request.app.state
    try:
        lock: TokenRefreshLockPort | None = state.ip_token_refresh_lock
    except AttributeError:
        lock = None
    if lock is None:
        try:
            db_router: DatabaseRouterPort | None = state.db_router
        except AttributeError:
            db_router = None
        lock = _get_api_provider(request).create_token_refresh_lock(db_router=db_router)
        state.ip_token_refresh_lock = lock
    return lock


def get_token_refresher(request: Request) -> OAuth2TokenRefresherPort:
    """Resolves the OAuth2TokenRefresherPort configured with IP settings from application state."""
    state = request.app.state
    try:
        refresher: OAuth2TokenRefresherPort | None = state.ip_token_refresher
    except AttributeError:
        refresher = None
    if refresher is None:
        refresher = _get_api_provider(request).create_token_refresher()
        state.ip_token_refresher = refresher
    return refresher


def get_token_manager(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    cipher: Annotated[CipherPort, Depends(get_cipher)],
    token_refresher: Annotated[OAuth2TokenRefresherPort, Depends(get_token_refresher)],
    lock_port: Annotated[TokenRefreshLockPort, Depends(get_token_refresh_lock)],
) -> TokenManagerService:
    """Resolves the configured TokenManagerService for OAuth2 token freshness across IP operations."""
    return TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        token_refresher=token_refresher,
        lock_port=lock_port,
    )


def get_list_connection_entities_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ListConnectionEntitiesUseCase:
    """Resolves ListConnectionEntitiesUseCase bound to the request Control Plane UoW."""
    return ListConnectionEntitiesUseCase(control_plane_uow=cp_uow)


def get_add_connection_entity_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> AddConnectionEntityUseCase:
    """Resolves AddConnectionEntityUseCase bound to the request Control Plane UoW."""
    return AddConnectionEntityUseCase(control_plane_uow=cp_uow)


def get_update_connection_entity_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> UpdateConnectionEntityUseCase:
    """Resolves UpdateConnectionEntityUseCase bound to the request Control Plane UoW."""
    return UpdateConnectionEntityUseCase(control_plane_uow=cp_uow)


def get_remove_connection_entity_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> RemoveConnectionEntityUseCase:
    """Resolves RemoveConnectionEntityUseCase bound to the request Control Plane UoW."""
    return RemoveConnectionEntityUseCase(control_plane_uow=cp_uow)


def get_reset_connection_entity_checkpoint_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ResetConnectionEntityCheckpointUseCase:
    """Resolves ResetConnectionEntityCheckpointUseCase bound to the request Control Plane UoW."""
    return ResetConnectionEntityCheckpointUseCase(control_plane_uow=cp_uow)


def get_discover_catalog_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    cipher: Annotated[CipherPort, Depends(get_cipher)],
    connectors: Annotated[Mapping[str, ConnectorPort], Depends(get_connectors)],
    token_manager: Annotated[TokenManagerService, Depends(get_token_manager)],
) -> DiscoverCatalogUseCase:
    """Resolves DiscoverCatalogUseCase bound to request-scoped Control Plane dependencies."""
    return DiscoverCatalogUseCase(
        uow=cp_uow,
        cipher=cipher,
        connectors=connectors,
        token_manager=token_manager,
    )


def get_trigger_sync_run_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> TriggerSyncRunUseCase:
    """Resolves TriggerSyncRunUseCase bound to the request Control Plane UoW."""
    return TriggerSyncRunUseCase(control_plane_uow=cp_uow)


def get_list_sync_runs_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ListSyncRunsUseCase:
    """Resolves ListSyncRunsUseCase bound to the request Control Plane UoW."""
    return ListSyncRunsUseCase(control_plane_uow=cp_uow)


def get_get_sync_run_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> GetSyncRunUseCase:
    """Resolves GetSyncRunUseCase bound to the request Control Plane UoW."""
    return GetSyncRunUseCase(control_plane_uow=cp_uow)


def get_receive_push_executor_factory(
    tiered_storage: Annotated[TieredStoragePort, Depends(get_tiered_storage)],
    verifier: Annotated[InboundVerifierPort, Depends(get_inbound_verifier)],
    decoder: Annotated[InboundPayloadDecoderPort, Depends(get_inbound_decoder)],
    ack: Annotated[InboundAckPort, Depends(get_inbound_ack)],
) -> ReceivePushExecutorFactory:
    """Resolves a factory creating ReceivePushExecutorPort instances for Data Plane UoWs."""

    def _create_push_executor(dp_uow: IpDataPlaneUnitOfWorkPort) -> ReceivePushExecutorPort:
        return ReceivePushUseCase(
            uow=dp_uow,
            tiered_storage=tiered_storage,
            verifier=verifier,
            decoder=decoder,
            ack=ack,
        )

    return _create_push_executor


def get_ingest_connection_webhook_use_case(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    push_executor_factory: Annotated[
        ReceivePushExecutorFactory, Depends(get_receive_push_executor_factory)
    ],
) -> IngestConnectionWebhookUseCase:
    """Resolves IngestConnectionWebhookUseCase orchestrating L1 webhook ingestion."""
    return IngestConnectionWebhookUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        push_executor_factory=push_executor_factory,
    )


def get_transformer_registry(request: Request) -> TransformerRegistryPort:
    """Provides the app-scoped TransformerRegistryPort from application state."""
    state = request.app.state
    try:
        registry: TransformerRegistryPort | None = state.ip_transformer_registry
    except AttributeError:
        registry = None
    if registry is None:
        registry = _get_api_provider(request).create_transformer_registry()
        state.ip_transformer_registry = registry
    return registry


def get_stitch_catalog_registry(request: Request) -> StitchCatalogRegistryPort:
    """Provides the app-scoped StitchCatalogRegistryPort from application state."""
    state = request.app.state
    try:
        registry: StitchCatalogRegistryPort | None = state.ip_stitch_catalog
    except AttributeError:
        registry = None
    if registry is None:
        catalog = _get_api_provider(request).create_stitch_catalog_registry()
        state.ip_stitch_catalog = catalog
        return catalog
    return registry


def get_workflow_definition_registry(request: Request) -> WorkflowDefinitionRegistryPort:
    """Provides the app-scoped WorkflowDefinitionRegistryPort from application state."""
    state = request.app.state
    try:
        registry: WorkflowDefinitionRegistryPort | None = state.ip_workflow_definitions
    except AttributeError:
        registry = None
    if registry is None:
        registry = _get_api_provider(request).create_workflow_definition_registry()
        state.ip_workflow_definitions = registry
    return registry


def get_stitch_shard_gateway(
    request: Request,
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
    definition_registry: Annotated[
        WorkflowDefinitionRegistryPort, Depends(get_workflow_definition_registry)
    ],
) -> StitchShardGatewayPort:
    """Provides a shard-aware gateway for dispatching canonical events and querying Stitch runs."""
    db_router: DatabaseRouterPort = request.app.state.db_router
    return _get_api_provider(request).create_stitch_shard_gateway(
        db_router=db_router,
        dp_uow_provider=dp_uow_provider,
        stitch_catalog=stitch_catalog,
        definition_registry=definition_registry,
    )


def get_ip_stage_replay_processors(
    request: Request,
) -> Mapping[PipelineStage, StageReplayProcessorPort]:
    """Assembles the isolated StageReplayProcessorPort strategies for inbound replay endpoints."""
    return _get_api_provider(request).get_stage_replay_processors()


def get_columnar_batch_processor(
    request: Request,
) -> ColumnarBatchProcessorPort:
    """Resolves the ColumnarBatchProcessorPort from the IP API Provider."""
    return _get_api_provider(request).get_columnar_batch_processor()


def get_interval_rollup_repository(
    request: Request,
) -> IntervalRollupRepositoryPort:
    """Resolves the IntervalRollupRepositoryPort from the IP API Provider."""
    state = request.app.state
    try:
        repo: IntervalRollupRepositoryPort | None = state.ip_interval_rollup_repository
    except AttributeError:
        repo = None
    if repo is None:
        repo = _get_api_provider(request).get_interval_rollup_repository()
        state.ip_interval_rollup_repository = repo
    return repo


__all__ = [
    "get_add_connection_entity_use_case",
    "get_catalog_registry",
    "get_cipher",
    "get_columnar_batch_processor",
    "get_connectors",
    "get_discover_catalog_use_case",
    "get_effective_ucp_tenant_id",
    "get_get_sync_run_use_case",
    "get_inbound_ack",
    "get_inbound_decoder",
    "get_inbound_verifier",
    "get_ingest_connection_webhook_use_case",
    "get_interval_rollup_repository",
    "get_ip_control_plane_uow",
    "get_ip_data_plane_uow_provider",
    "get_ip_global_session",
    "get_ip_stage_replay_processors",
    "get_list_connection_entities_use_case",
    "get_list_sync_runs_use_case",
    "get_receive_push_executor_factory",
    "get_remove_connection_entity_use_case",
    "get_reset_connection_entity_checkpoint_use_case",
    "get_stitch_catalog_registry",
    "get_stitch_shard_gateway",
    "get_tenant_repository",
    "get_tiered_storage",
    "get_token_manager",
    "get_token_refresh_lock",
    "get_token_refresher",
    "get_transformer_registry",
    "get_trigger_sync_run_use_case",
    "get_update_connection_entity_use_case",
    "get_workflow_definition_registry",
    "require_canonical_records_read",
    "require_flows_read",
    "require_flows_write",
    "require_ip_permission",
    "require_raw_records_read",
    "require_sync_trigger",
    "require_tenant_member",
    "resolve_tenant_id_by_slug",
]
