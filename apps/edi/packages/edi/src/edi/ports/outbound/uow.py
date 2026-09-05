from types import TracebackType
from typing import Protocol

from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.control_plane_outbox_repository_port import (
    ControlPlaneOutboxRepositoryPort,
)
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.platform_settings_repository import PlatformSettingsRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from edi.ports.outbound.trace_repository import TraceRepositoryPort
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort


class ControlPlaneUnitOfWorkPort(Protocol):
    """
    Unit of Work Port for the Control Plane (Global Schema).
    Exposes abstract repository interfaces.
    """

    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    tenants: TenantRepositoryPort
    edi_headers: EdiHeaderRepositoryPort
    platform_settings: PlatformSettingsRepositoryPort
    control_plane_outbox: ControlPlaneOutboxRepositoryPort

    async def __aenter__(self) -> "ControlPlaneUnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class DataPlaneUnitOfWorkPort(Protocol):
    """
    Unit of Work Port for the Data Plane (Tenant Schema).
    Exposes abstract repository interfaces.
    """

    transactions: TransactionRepositoryPort
    traces: TraceRepositoryPort

    async def __aenter__(self) -> "DataPlaneUnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
