from typing import Protocol

from domain.models import OutboundRouteDomainModel

from api.domain.models import CreateOutboundRouteCmd, UpdateOutboundRouteCmd


class OutboundRouteRepositoryPort(Protocol):
    async def create_outbound_route(self, tenant_id: str, cmd: CreateOutboundRouteCmd) -> str: ...
    async def update_outbound_route(
        self, tenant_id: str, route_id: str, cmd: UpdateOutboundRouteCmd
    ) -> bool: ...
    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> bool: ...
    async def get_outbound_route(
        self, tenant_id: str, route_id: str
    ) -> OutboundRouteDomainModel | None: ...
    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRouteDomainModel | None: ...
    async def list_outbound_routes(self, tenant_id: str) -> list[OutboundRouteDomainModel]: ...
