from typing import Any, Protocol

from api.ports.api_token_repository import ApiTokenRepositoryPort
from api.ports.as2_partner_repository import AS2TradingPartnerRepositoryPort
from api.ports.as2_partnership_repository import AS2PartnershipRepositoryPort
from api.ports.edi_header_repository import EdiHeaderRepositoryPort
from api.ports.inbound_route_repository import InboundRouteRepositoryPort
from api.ports.outbound_route_repository import OutboundRouteRepositoryPort
from api.ports.outbox_repository import (
    ControlPlaneOutboxRepositoryPort,
    DataPlaneOutboxRepositoryPort,
)
from api.ports.platform_settings_repository import PlatformSettingsRepositoryPort
from api.ports.sftp_repository import SFTPPartnerRepositoryPort
from api.ports.tenant_repository import TenantRepositoryPort
from api.ports.transaction_repository import TransactionRepositoryPort
from api.ports.webhook_repository import WebhookRepositoryPort


class ControlPlaneUnitOfWorkPort(Protocol):
    """
    Unit of Work Port for the Control Plane (Global Schema).
    Exposes abstract repository interfaces.
    """

    api_tokens: ApiTokenRepositoryPort
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
