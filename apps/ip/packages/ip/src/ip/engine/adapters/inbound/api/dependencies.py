"""FastAPI dependencies and perimeter tenant guard for Integration Platform API routers."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator, Mapping
from typing import Annotated

import structlog
from database.models.identity import Tenant as TenantORM
from database.provider import DatabaseProvider
from database.router import DatabaseRouterPort
from fastapi import Depends, HTTPException, Path, Request, status
from identity.domain.identity_context import IdentityContext
from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.application.stitches.registry_loader import (
    create_default_workflow_definition_registry,
    register_default_stitches,
)
from ip.application.transformers.registry_loader import create_default_transformer_registry
from ip.engine.adapters.outbound.auth.oauth2_strategy import OAuth2StrategyTokenRefresher
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    SqlAlchemyTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    stage_workflow_outbox_event,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.adapters.outbound.inbound.ack import StandardInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import NoOpVerifier
from ip.engine.adapters.outbound.stitches.sharded_stitch_adapters import (
    IpShardedStitchCanonicalDispatcherAdapter,
)
from ip.engine.adapters.outbound.stitches.stitch_catalog_registry import (
    InMemoryStitchCatalogRegistry,
)
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
    StitchShardGatewayPort,
)
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    TokenRefreshLockPort,
)
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.engine.settings import get_ip_engine_settings
from orchestration.adapters.outbound.database.uow import SqlAlchemyWorkflowUnitOfWork
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from orchestration.ports.outbound import WorkflowUnitOfWorkPort
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def get_ip_global_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """Yields a request-scoped Control Plane GlobalSession from the host shell's DatabaseProvider."""
    db_provider: DatabaseProvider = request.app.state.db_provider
    async with db_provider.session() as session:
        yield session


def get_ip_control_plane_uow(
    global_session: Annotated[AsyncSession, Depends(get_ip_global_session)],
) -> IpControlPlaneUnitOfWorkPort:
    """Resolves an IpControlPlaneUnitOfWorkPort bound to the request Control Plane session."""
    return SqlAlchemyIpControlPlaneUnitOfWork(global_session=global_session)


def get_ip_data_plane_uow_provider(request: Request) -> IpDataPlaneUnitOfWorkProviderPort:
    """Resolves the IpDataPlaneUnitOfWorkProviderPort bound to the centralized DatabaseRouter and IpTenantResolver."""
    state = request.app.state
    db_router: DatabaseRouterPort = state.db_router
    try:
        resolver: IpTenantResolver | None = state.ip_tenant_resolver
    except AttributeError:
        resolver = None
    if resolver is None:
        resolver = IpTenantResolver(db_router)
        state.ip_tenant_resolver = resolver

    try:
        storage: TieredStoragePort | None = state.ip_tiered_storage
    except AttributeError:
        storage = None
    if storage is None:
        storage = TieredStorageAdapter()
        state.ip_tiered_storage = storage

    return IpTenantUoWProvider(resolver=resolver, db_router=db_router, storage=storage)


async def require_tenant_member(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_ip_global_session)],
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
        result = await session.execute(
            select(TenantORM.id).where(TenantORM.idp_tenant_id == tenant_id)
        )
        resolved_id = result.scalar_one_or_none()
        canonical_tenant_id = str(resolved_id) if resolved_id is not None else tenant_id
        if session.in_transaction():
            await session.commit()
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


class _ConnectorCatalogMapping(Mapping[str, ConnectorPort]):
    """Read-only Mapping adapter over CatalogRegistryPort."""

    def __init__(self, registry: CatalogRegistryPort) -> None:
        self._registry = registry

    def __getitem__(self, key: str) -> ConnectorPort:
        result = self._registry.get_connector(key)
        if result.is_ok and result.value is not None:
            return result.value
        raise KeyError(key)

    def __len__(self) -> int:
        return len(self._registry.list_apps())

    def __iter__(self) -> Iterator[str]:
        return (app.app_id for app in self._registry.list_apps())


def get_catalog_registry() -> CatalogRegistryPort:
    """Resolves a CatalogRegistryPort configured according to IP engine settings."""
    settings = get_ip_engine_settings()
    return create_default_catalog_registry(allow_private_ips=settings.allow_private_ips)


def get_connectors(
    registry: Annotated[CatalogRegistryPort, Depends(get_catalog_registry)],
) -> Mapping[str, ConnectorPort]:
    """Resolves a Mapping[str, ConnectorPort] backed by CatalogRegistryPort."""
    return _ConnectorCatalogMapping(registry)


def get_cipher() -> CipherPort:
    """Resolves the platform CipherPort."""
    return SecurityProvider.get_cipher()


def get_tiered_storage() -> TieredStoragePort:
    """Resolves the TieredStoragePort backed by platform S3 PayloadStoragePort."""
    return TieredStorageAdapter()


def get_inbound_verifier() -> InboundVerifierPort:
    """Resolves the InboundVerifierPort for L1 push webhook verification."""
    return NoOpVerifier()


def get_inbound_decoder() -> InboundPayloadDecoderPort:
    """Resolves the InboundPayloadDecoderPort for L1 push webhook payload decoding."""
    return StandardInboundPayloadDecoder()


def get_inbound_ack() -> InboundAckPort:
    """Resolves the InboundAckPort for L1 push webhook acknowledgments."""
    return StandardInboundAck()


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
        lock = SqlAlchemyTokenRefreshLockAdapter(db_router=db_router)
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
        settings = get_ip_engine_settings()
        refresher = OAuth2StrategyTokenRefresher(allow_private_ips=settings.allow_private_ips)
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


def get_transformer_registry(request: Request) -> TransformerRegistryPort:
    """Provides the app-scoped TransformerRegistryPort from application state."""
    state = request.app.state
    try:
        registry: TransformerRegistryPort | None = state.ip_transformer_registry
    except AttributeError:
        registry = None
    if registry is None:
        registry = create_default_transformer_registry()
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
        catalog = InMemoryStitchCatalogRegistry()
        register_default_stitches(catalog)
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
        registry = create_default_workflow_definition_registry()
        state.ip_workflow_definitions = registry
    return registry


def _build_workflow_uow(session: AsyncSession) -> WorkflowUnitOfWorkPort:
    return SqlAlchemyWorkflowUnitOfWork(
        session,
        outbox_sink=lambda tid, et, ik, pl: stage_workflow_outbox_event(session, tid, et, ik, pl),
    )


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
    return IpShardedStitchCanonicalDispatcherAdapter(
        db_router=db_router,
        dp_uow_provider=dp_uow_provider,
        stitch_catalog=stitch_catalog,
        definition_registry=definition_registry,
        workflow_uow_factory=_build_workflow_uow,
        control_plane_uow_factory=SqlAlchemyIpControlPlaneUnitOfWork,
    )


__all__ = [
    "get_catalog_registry",
    "get_cipher",
    "get_connectors",
    "get_inbound_ack",
    "get_inbound_decoder",
    "get_inbound_verifier",
    "get_ip_control_plane_uow",
    "get_ip_data_plane_uow_provider",
    "get_ip_global_session",
    "get_stitch_catalog_registry",
    "get_stitch_shard_gateway",
    "get_tiered_storage",
    "get_token_manager",
    "get_token_refresh_lock",
    "get_token_refresher",
    "get_transformer_registry",
    "get_workflow_definition_registry",
    "require_tenant_member",
]
