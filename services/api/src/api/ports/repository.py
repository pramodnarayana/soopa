from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookCmd,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
    UpdateSFTPPartnerCmd,
)


class AS2TradingPartnerRepositoryPort(Protocol):
    async def create_as2_identity(
        self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd
    ) -> UUID: ...
    async def update_as2_identity(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> None: ...
    async def get_as2_partner(self, tenant_id: int, partner_id: UUID) -> Any: ...
    async def delete_as2_identity(self, tenant_id: int, partner_id: UUID) -> None: ...
    async def get_as2_partners_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]: ...
    async def list_as2_partners(self, tenant_id: int) -> Sequence[Any]: ...


class AS2PartnershipRepositoryPort(Protocol):
    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> UUID: ...
    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> None: ...
    async def get_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> Any: ...
    async def delete_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> None: ...
    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[Any, Any, Any] | None: ...


class SFTPPartnerRepositoryPort(Protocol):
    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> UUID: ...
    async def update_sftp_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateSFTPPartnerCmd
    ) -> None: ...
    async def delete_sftp_partner(self, tenant_id: int, partner_id: UUID) -> None: ...
    async def get_sftp_partner(self, tenant_id: int, partner_id: UUID) -> Any: ...
    async def list_sftp_partners(self, tenant_id: int) -> Sequence[Any]: ...
    async def get_sftp_partners_by_ids(
        self, tenant_id: int, ids: list[UUID]
    ) -> dict[UUID, str]: ...


class WebhookRepositoryPort(Protocol):
    async def create_webhook(self, tenant_id: int, cmd: CreateWebhookCmd) -> UUID: ...
    async def get_webhook(self, tenant_id: int, webhook_id: UUID) -> Any: ...
    async def list_webhooks(self, tenant_id: int) -> Sequence[Any]: ...
    async def get_webhooks_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]: ...


class RouteRepositoryPort(Protocol):
    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> UUID: ...
    async def update_inbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateInboundRouteCmd
    ) -> bool: ...
    async def delete_inbound_route(self, tenant_id: int, route_id: UUID) -> bool: ...

    async def create_outbound_route(self, tenant_id: int, cmd: CreateOutboundRouteCmd) -> UUID: ...
    async def update_outbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool: ...
    async def delete_outbound_route(self, tenant_id: int, route_id: UUID) -> bool: ...

    async def get_all_routes(self, tenant_id: int) -> dict[str, list[Any]]: ...


class OutboxRepositoryPort(Protocol):
    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID: ...


class ControlPlaneRepositoryPort(
    AS2TradingPartnerRepositoryPort,
    AS2PartnershipRepositoryPort,
    SFTPPartnerRepositoryPort,
    WebhookRepositoryPort,
    RouteRepositoryPort,
    OutboxRepositoryPort,
    Protocol,
):
    """
    Aggregate Port for the Control Plane repository, handling Global AS2 configs and Tenant configs as SoT.
    This maintains backward compatibility while segregating interfaces.
    """

    pass


class DataPlaneRepositoryPort(Protocol):
    """
    Port for the Data Plane repository, handling Operational Data.
    """

    async def create_edi_message(self, tenant_id: int, payload: dict[str, Any]) -> UUID:
        """
        Saves a new EdiMessage record to the Data Plane.
        """
        ...

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        """
        Saves an outbox event to the Data Plane.
        """
        ...


class TenantRepositoryPort(Protocol):
    """
    Port for retrieving tenant-level configuration globally.
    """

    async def get_tenant_flags(self, tenant_id: int) -> dict[str, Any] | None: ...
