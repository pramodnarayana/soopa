"""Concrete IpApiProviderPort Composition Root factory bound onto `app.state.ip_api_provider`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager

from database.router import DatabaseRouterPort
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider
from sqlalchemy.ext.asyncio import AsyncSession

from ip.engine.application.api_provider_port import IpApiProviderPort
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.bootstrap.container import (
    DomainRepositoryFactory,
    create_default_stage_replay_processors,
    create_default_stitch_catalog,
    create_empty_transformer_registry,
    create_empty_workflow_definition_registry,
    create_engine_catalog_registry,
    create_ip_columnar_batch_processor,
    create_ip_control_plane_uow,
    create_ip_inbound_ack,
    create_ip_inbound_decoder,
    create_ip_inbound_verifier,
    create_ip_interval_rollup_repository,
    create_ip_scoped_tenant_repository,
    create_ip_stitch_dispatcher,
    create_ip_tenant_repository,
    create_ip_tenant_resolver,
    create_ip_tenant_uow_provider,
    create_ip_tiered_storage,
    create_ip_token_refresh_lock,
    create_ip_token_refresher,
)
from ip.engine.domain.enums import PipelineStage
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.engine.ports.outbound.columnar_batch_processor_port import ColumnarBatchProcessorPort
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
    IpDataPlaneUnitOfWorkProviderPort,
    IpTenantResolverPort,
)
from ip.engine.settings import get_ip_engine_settings


class IpApiProvider(IpApiProviderPort[AsyncSession, DatabaseRouterPort]):
    """Domain-agnostic Composition Root implementation of IpApiProviderPort."""

    def __init__(
        self,
        *,
        catalog_registry_factory: Callable[[bool], CatalogRegistryPort] | None = None,
        transformer_registry_factory: Callable[[], TransformerRegistryPort] | None = None,
        stitch_catalog_factory: Callable[[], StitchCatalogRegistryPort] | None = None,
        workflow_definition_registry_factory: Callable[[], WorkflowDefinitionRegistryPort]
        | None = None,
        domain_repository_factories: Mapping[str, DomainRepositoryFactory] | None = None,
        columnar_batch_processor: ColumnarBatchProcessorPort | None = None,
        interval_rollup_repository: IntervalRollupRepositoryPort | None = None,
    ) -> None:
        self._catalog_registry_factory = catalog_registry_factory
        self._transformer_registry_factory = (
            transformer_registry_factory or create_empty_transformer_registry
        )
        self._stitch_catalog_factory = stitch_catalog_factory or create_default_stitch_catalog
        self._workflow_definition_registry_factory = (
            workflow_definition_registry_factory or create_empty_workflow_definition_registry
        )
        self._domain_repository_factories = domain_repository_factories
        self._columnar_batch_processor = (
            columnar_batch_processor or create_ip_columnar_batch_processor()
        )
        self._interval_rollup_repository = (
            interval_rollup_repository or create_ip_interval_rollup_repository()
        )

    def create_control_plane_uow(
        self, global_session: AsyncSession
    ) -> IpControlPlaneUnitOfWorkPort:
        return create_ip_control_plane_uow(global_session)

    def create_tenant_repository(self, global_session: AsyncSession) -> TenantRepositoryPort:
        return create_ip_tenant_repository(global_session)

    def create_scoped_tenant_repository(
        self,
        session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> TenantRepositoryPort:
        return create_ip_scoped_tenant_repository(session_scope)

    def resolve_data_plane_uow_provider(
        self,
        *,
        db_router: DatabaseRouterPort,
        resolver: IpTenantResolverPort | None,
        storage: TieredStoragePort | None,
    ) -> tuple[IpDataPlaneUnitOfWorkProviderPort, IpTenantResolverPort, TieredStoragePort]:
        resolved_resolver = resolver or create_ip_tenant_resolver(db_router)
        resolved_storage = storage or create_ip_tiered_storage()
        provider = create_ip_tenant_uow_provider(
            resolver=resolved_resolver,
            db_router=db_router,
            storage=resolved_storage,
            domain_repository_factories=self._domain_repository_factories,
        )
        return provider, resolved_resolver, resolved_storage

    def get_catalog_registry(self) -> CatalogRegistryPort:
        settings = get_ip_engine_settings()
        if self._catalog_registry_factory is not None:
            return self._catalog_registry_factory(settings.allow_private_ips)
        return create_engine_catalog_registry(allow_private_ips=settings.allow_private_ips)

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

    def create_token_refresh_lock(
        self, db_router: DatabaseRouterPort | None
    ) -> TokenRefreshLockPort:
        return create_ip_token_refresh_lock(db_router=db_router)

    def create_token_refresher(self) -> OAuth2TokenRefresherPort:
        settings = get_ip_engine_settings()
        return create_ip_token_refresher(allow_private_ips=settings.allow_private_ips)

    def create_transformer_registry(self) -> TransformerRegistryPort:
        return self._transformer_registry_factory()

    def create_stitch_catalog_registry(self) -> StitchCatalogRegistryPort:
        return self._stitch_catalog_factory()

    def create_workflow_definition_registry(self) -> WorkflowDefinitionRegistryPort:
        return self._workflow_definition_registry_factory()

    def create_stitch_shard_gateway(
        self,
        *,
        db_router: DatabaseRouterPort,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stitch_catalog: StitchCatalogRegistryPort,
        definition_registry: WorkflowDefinitionRegistryPort,
    ) -> StitchShardGatewayPort:
        return create_ip_stitch_dispatcher(
            db_router=db_router,
            dp_uow_provider=dp_uow_provider,
            stitch_catalog=stitch_catalog,
            definition_registry=definition_registry,
        )

    def get_stage_replay_processors(
        self,
    ) -> Mapping[PipelineStage, StageReplayProcessorPort]:
        return create_default_stage_replay_processors()

    def get_columnar_batch_processor(self) -> ColumnarBatchProcessorPort:
        return self._columnar_batch_processor

    def get_interval_rollup_repository(self) -> IntervalRollupRepositoryPort:
        return self._interval_rollup_repository


__all__ = ["IpApiProvider"]
