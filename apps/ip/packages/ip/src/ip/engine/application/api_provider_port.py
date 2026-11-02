"""Application-layer inbound DI port decoupling FastAPI adapters from the IP Composition Root."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from security.ports.cipher_port import CipherPort

from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
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


class IpApiProviderPort(Protocol):
    """Port attached to `app.state.ip_api_provider` by the IP Composition Root."""

    def create_control_plane_uow(self, global_session: object) -> IpControlPlaneUnitOfWorkPort: ...

    def resolve_data_plane_uow_provider(
        self,
        *,
        db_router: object,
        resolver: IpTenantResolverPort | None,
        storage: TieredStoragePort | None,
    ) -> tuple[IpDataPlaneUnitOfWorkProviderPort, IpTenantResolverPort, TieredStoragePort]: ...

    async def resolve_canonical_tenant_id(
        self, global_session: object, idp_tenant_id: str
    ) -> str | None: ...

    def get_catalog_registry(self) -> CatalogRegistryPort: ...

    def get_cipher(self) -> CipherPort: ...

    def get_tiered_storage(self) -> TieredStoragePort: ...

    def get_inbound_verifier(self) -> InboundVerifierPort: ...

    def get_inbound_decoder(self) -> InboundPayloadDecoderPort: ...

    def get_inbound_ack(self) -> InboundAckPort: ...

    def create_token_refresh_lock(self, db_router: object | None) -> TokenRefreshLockPort: ...

    def create_token_refresher(self) -> OAuth2TokenRefresherPort: ...

    def create_transformer_registry(self) -> TransformerRegistryPort: ...

    def create_stitch_catalog_registry(self) -> StitchCatalogRegistryPort: ...

    def create_workflow_definition_registry(self) -> WorkflowDefinitionRegistryPort: ...

    def create_stitch_shard_gateway(
        self,
        *,
        db_router: object,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stitch_catalog: StitchCatalogRegistryPort,
        definition_registry: WorkflowDefinitionRegistryPort,
    ) -> StitchShardGatewayPort: ...

    def get_stage_replay_processors(
        self,
    ) -> Mapping[PipelineStage, StageReplayProcessorPort]: ...


__all__ = ["IpApiProviderPort"]
