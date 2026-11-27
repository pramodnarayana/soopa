from typing import Protocol

from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.routing.isa_resolution import IsaTenantResolution


class InboundRouteRepositoryPort(Protocol):
    async def save(self, aggregate: InboundRoute) -> None: ...
    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRoute | None: ...
    async def get_inbound_route_by_id(
        self, tenant_id: str, route_id: str
    ) -> InboundRoute | None: ...
    async def resolve_tenant_by_isa(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        *,
        transaction_type: str | None = None,
    ) -> IsaTenantResolution: ...
    async def delete(self, aggregate: InboundRoute) -> None: ...
    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRoute]: ...
