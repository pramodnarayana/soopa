from typing import Protocol

from edi.domain.models.inbound_routes import InboundRouteDomainModel


class InboundRouteRepositoryPort(Protocol):
    async def save(self, aggregate: InboundRouteDomainModel) -> None: ...
    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRouteDomainModel | None: ...
    async def get_inbound_route_by_id(
        self, tenant_id: str, route_id: str
    ) -> InboundRouteDomainModel | None: ...
    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None: ...
    async def delete(self, aggregate: InboundRouteDomainModel) -> None: ...
    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]: ...
