from types import TracebackType
from typing import Protocol

from edi.ports.outbound.api_gateway_repository import ApiGatewayRepositoryPort
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.control_plane_outbox_repository_port import (
    ControlPlaneOutboxRepositoryPort,
)
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.settings_repository import SettingsRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from edi.ports.outbound.trace_repository import TraceRepositoryPort
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


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
    settings: SettingsRepositoryPort
    control_plane_outbox: ControlPlaneOutboxRepositoryPort
    webhooks: WebhookRepositoryPort

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

    api_gateway_transactions: ApiGatewayRepositoryPort
    transactions: TransactionRepositoryPort
    traces: TraceRepositoryPort
    outbox: DataPlaneOutboxRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    webhooks: WebhookRepositoryPort
    edi_headers: EdiHeaderRepositoryPort

    async def __aenter__(self) -> "DataPlaneUnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool: ...

    async def has_been_processed(self, tenant_id: str, idempotency_key: str) -> bool: ...
