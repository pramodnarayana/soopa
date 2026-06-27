from typing import Any, Protocol
from uuid import UUID

from api.domain.models import CreateTradingPartnerRequest


class ControlPlaneRepositoryPort(Protocol):
    """
    Port for the Control Plane repository, ensuring zero leakage of SQLAlchemy
    into the Provisioning Service.
    """

    async def create_trading_partner(
        self, tenant_id: int, partner_name: str, as2_id: str | None, direction: str
    ) -> UUID:
        """Inserts a Trading Partner in the Global DB and returns its UUID."""
        ...

    async def create_connection(
        self, trading_partner_id: UUID, tenant_id: int, request: CreateTradingPartnerRequest
    ) -> UUID:
        """Inserts a Connection for the Trading Partner."""
        ...

    async def create_outbox_event(self, event_type: str, payload: dict[str, Any]) -> UUID:
        """Inserts an Outbox event into the Global DB."""
        ...
