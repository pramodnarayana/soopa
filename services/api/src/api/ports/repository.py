from typing import Any, Protocol
from uuid import UUID

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
)


class ControlPlaneRepositoryPort(Protocol):
    """
    Port for the Control Plane repository, handling Global AS2 configs.
    """

    async def create_as2_identity(self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd) -> UUID:
        """Inserts an AS2 Partner in the Global DB and returns its UUID."""
        ...

    async def create_as2_partnership(self, tenant_id: int, cmd: CreateAS2PartnershipCmd) -> UUID:
        """Inserts an AS2 Partnership in the Global DB and returns its UUID."""
        ...

    async def get_as2_partners_by_ids(self, ids: list[UUID]) -> dict[UUID, str]:
        """Returns a dict mapping AS2 Partner ID to Name."""
        ...

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        """Inserts an Outbox event into the Global DB."""
        ...


class DataPlaneRepositoryPort(Protocol):
    """
    Port for the Data Plane repository, handling Tenant-specific configs directly.
    """

    async def create_sftp_partner(self, cmd: CreateSFTPPartnerCmd) -> UUID:
        """Inserts an SFTP Partner into the Tenant DB and returns its UUID."""
        ...

    async def get_sftp_partners_by_ids(self, ids: list[UUID]) -> dict[UUID, str]:
        """Returns a dict mapping SFTP Partner ID to Name."""
        ...

    async def get_webhook_partners_by_ids(self, ids: list[UUID]) -> dict[UUID, str]:
        """Returns a dict mapping Webhook Partner ID to Name."""
        ...

    async def create_webhook_partner(self, cmd: CreateWebhookPartnerCmd) -> UUID:
        """Inserts a Webhook Partner into the Tenant DB and returns its UUID."""
        ...

    async def create_inbound_route(self, cmd: CreateInboundRouteCmd) -> UUID:
        """Inserts an Inbound Route into the Tenant DB and returns its UUID."""
        ...

    async def create_outbound_route(self, cmd: CreateOutboundRouteCmd) -> UUID:
        """Inserts an Outbound Route into the Tenant DB and returns its UUID."""
        ...

    async def get_all_routes(self) -> dict[str, list[Any]]:
        """Retrieves all Inbound and Outbound Routes for the tenant."""
        ...


class TenantRepositoryPort(Protocol):
    """
    Port for retrieving tenant-level configuration globally.
    """

    async def get_tenant_flags(self, tenant_id: int) -> dict[str, Any] | None:
        """Retrieves tenant flags such as allow_private_as2."""
        ...
