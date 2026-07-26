from typing import Protocol
from uuid import UUID

from domain.models import OutboundRouteDomainModel

from api.domain.models import CreateOutboundRouteCmd, UpdateOutboundRouteCmd


class OutboundRouteRepositoryPort(Protocol):
    async def create_outbound_route(self, tenant_id: str, cmd: CreateOutboundRouteCmd) -> UUID: ...
    async def update_outbound_route(
        self, tenant_id: str, route_id: UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool: ...
    async def delete_outbound_route(self, tenant_id: str, route_id: UUID) -> bool: ...
    async def get_outbound_route(
        self, tenant_id: str, route_id: UUID
    ) -> OutboundRouteDomainModel | None: ...
    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRouteDomainModel | None: ...
    async def list_outbound_routes(self, tenant_id: str) -> list[OutboundRouteDomainModel]: ...
