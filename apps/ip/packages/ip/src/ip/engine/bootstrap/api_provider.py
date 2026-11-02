"""Concrete IpApiProviderPort Composition Root factory bound onto `app.state.ip_api_provider`."""

from __future__ import annotations

from collections.abc import Mapping

from database.models.identity import Tenant as TenantORM
from database.router import DatabaseRouterPort
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ip.engine.application.api_provider_port import IpApiProviderPort
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.bootstrap.container import (
    create_default_stage_replay_processors,
    create_default_stitch_catalog,
    create_ip_control_plane_uow,
    create_ip_inbound_ack,
    create_ip_inbound_decoder,
    create_ip_inbound_verifier,
    create_ip_stitch_dispatcher,
    create_ip_tenant_resolver,
    create_ip_tenant_uow_provider,
    create_ip_tiered_storage,
    create_ip_token_refresh_lock,
    create_ip_token_refresher,
)
from ip.engine.domain.enums import PipelineStage
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
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
    IpTenantResolverPort,
)
from ip.engine.settings import get_ip_engine_settings
from ip.solutions.connectors.registry_loader import create_default_catalog_registry
from ip.solutions.stitches.registry_loader import (
    create_default_workflow_definition_registry,
)
from ip.solutions.transformers.registry_loader import create_default_transformer_registry


def _as_async_session(handle: object) -> AsyncSession:
    if not isinstance(handle, AsyncSession):
        raise TypeError(f"Expected AsyncSession, received {type(handle).__name__}")
    return handle


def _as_db_router(handle: object) -> DatabaseRouterPort:
    if not isinstance(handle, DatabaseRouterPort):
        raise TypeError(f"Expected DatabaseRouterPort, received {type(handle).__name__}")
    return handle


class IpApiProvider(IpApiProviderPort):
    """Composition Root implementation of IpApiProviderPort."""

    def create_control_plane_uow(self, global_session: object) -> IpControlPlaneUnitOfWorkPort:
        return create_ip_control_plane_uow(_as_async_session(global_session))

    def resolve_data_plane_uow_provider(
        self,
        *,
        db_router: object,
        resolver: IpTenantResolverPort | None,
        storage: TieredStoragePort | None,
    ) -> tuple[IpDataPlaneUnitOfWorkProviderPort, IpTenantResolverPort, TieredStoragePort]:
        typed_router = _as_db_router(db_router)
        resolved_resolver = resolver or create_ip_tenant_resolver(typed_router)
        resolved_storage = storage or create_ip_tiered_storage()
        provider = create_ip_tenant_uow_provider(
            resolver=resolved_resolver,
            db_router=typed_router,
            storage=resolved_storage,
        )
        return provider, resolved_resolver, resolved_storage

    async def resolve_canonical_tenant_id(
        self, global_session: object, idp_tenant_id: str
    ) -> str | None:
        session = _as_async_session(global_session)
        result = await session.execute(
            select(TenantORM.id).where(TenantORM.idp_tenant_id == idp_tenant_id)
        )
        resolved_id = result.scalar_one_or_none()
        return str(resolved_id) if resolved_id is not None else None

    def get_catalog_registry(self) -> CatalogRegistryPort:
        settings = get_ip_engine_settings()
        return create_default_catalog_registry(allow_private_ips=settings.allow_private_ips)

    def get_cipher(self) -> CipherPort:
        return SecurityProvider.get_cipher()

    def get_tiered_storage(self) -> TieredStoragePort:
        return create_ip_tiered_storage()

    def get_inbound_verifier(self) -> InboundVerifierPort:
        return create_ip_inbound_verifier()

    def get_inbound_decoder(self) -> InboundPayloadDecoderPort:
        return create_ip_inbound_decoder()

    def get_inbound_ack(self) -> InboundAckPort:
        return create_ip_inbound_ack()

    def create_token_refresh_lock(self, db_router: object | None) -> TokenRefreshLockPort:
        typed_router = _as_db_router(db_router) if db_router is not None else None
        return create_ip_token_refresh_lock(db_router=typed_router)

    def create_token_refresher(self) -> OAuth2TokenRefresherPort:
        settings = get_ip_engine_settings()
        return create_ip_token_refresher(allow_private_ips=settings.allow_private_ips)

    def create_transformer_registry(self) -> TransformerRegistryPort:
        return create_default_transformer_registry()

    def create_stitch_catalog_registry(self) -> StitchCatalogRegistryPort:
        return create_default_stitch_catalog()

    def create_workflow_definition_registry(self) -> WorkflowDefinitionRegistryPort:
        return create_default_workflow_definition_registry()

    def create_stitch_shard_gateway(
        self,
        *,
        db_router: object,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stitch_catalog: StitchCatalogRegistryPort,
        definition_registry: WorkflowDefinitionRegistryPort,
    ) -> StitchShardGatewayPort:
        return create_ip_stitch_dispatcher(
            db_router=_as_db_router(db_router),
            dp_uow_provider=dp_uow_provider,
            stitch_catalog=stitch_catalog,
            definition_registry=definition_registry,
        )

    def get_stage_replay_processors(
        self,
    ) -> Mapping[PipelineStage, StageReplayProcessorPort]:
        return create_default_stage_replay_processors()


__all__ = ["IpApiProvider"]
