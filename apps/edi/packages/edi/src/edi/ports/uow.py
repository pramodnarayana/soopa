from typing import Any, Protocol

from edi.ports.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbox_repository import (
    ControlPlaneOutboxRepositoryPort,
    DataPlaneOutboxRepositoryPort,
)
from edi.ports.platform_settings_repository import PlatformSettingsRepositoryPort
from edi.ports.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.tenant_repository import TenantRepositoryPort
from edi.ports.transaction_repository import TransactionRepositoryPort
from edi.ports.webhook_repository import WebhookRepositoryPort


class ControlPlaneUnitOfWorkPort(Protocol):
    """
    Unit of Work Port for the Control Plane (Global Schema).
    Exposes abstract repository interfaces.
    """

    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    control_plane_outbox: ControlPlaneOutboxRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    tenants: TenantRepositoryPort
    webhooks: WebhookRepositoryPort
    edi_headers: EdiHeaderRepositoryPort
    platform_settings: PlatformSettingsRepositoryPort

    async def __aenter__(self) -> "ControlPlaneUnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class DataPlaneUnitOfWorkPort(Protocol):
    """
    Unit of Work Port for the Data Plane (Tenant Schema).
    Exposes abstract repository interfaces.
    """

    transactions: TransactionRepositoryPort
    data_plane_outbox: DataPlaneOutboxRepositoryPort

    async def __aenter__(self) -> "DataPlaneUnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
