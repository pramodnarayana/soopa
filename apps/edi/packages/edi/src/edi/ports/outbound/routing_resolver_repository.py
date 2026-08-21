from typing import Protocol

from domain.models import ConnectionType


class RoutingResolverRepositoryPort(Protocol):
    async def resolve_outbound_route(
        self, trading_partner_id: str
    ) -> tuple[str, ConnectionType] | None: ...

    async def resolve_as2_inbound(self, as2_from: str) -> tuple[str, ConnectionType] | None: ...

    async def resolve_inbound_route(
        self, sender_id: str, receiver_id: str, transaction_type: str | None
    ) -> tuple[str, ConnectionType] | None: ...

    async def resolve_business_metadata(self, partner_ids: list[str]) -> str | None: ...
