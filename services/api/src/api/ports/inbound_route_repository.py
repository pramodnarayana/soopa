from typing import Protocol
from uuid import UUID

from api.domain.models import CreateInboundRouteCmd, UpdateInboundRouteCmd
from domain.models import InboundRouteDomainModel


class InboundRouteRepositoryPort(Protocol):
    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> UUID: ...
    async def update_inbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateInboundRouteCmd
    ) -> bool: ...
    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: int,
        transaction_type: str | None = None,
    ) -> InboundRouteDomainModel | None: ...
    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> int | None: ...
    async def delete_inbound_route(self, tenant_id: int, route_id: UUID) -> bool: ...
