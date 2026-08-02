from typing import Protocol

from domain.models import InboundRouteDomainModel

from api.domain.models import CreateInboundRouteCmd, UpdateInboundRouteCmd


class InboundRouteRepositoryPort(Protocol):
    async def create_inbound_route(self, tenant_id: str, cmd: CreateInboundRouteCmd) -> str: ...
    async def update_inbound_route(
        self, tenant_id: str, route_id: str, cmd: UpdateInboundRouteCmd
    ) -> bool: ...
    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRouteDomainModel | None: ...
    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None: ...
    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> bool: ...
    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]: ...
