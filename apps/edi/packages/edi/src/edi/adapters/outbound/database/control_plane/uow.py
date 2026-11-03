from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.control_plane_outbox_repository_port import (
    ControlPlaneOutboxRepositoryPort,
)
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.settings_repository import SettingsRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


class SqlAlchemyControlPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """
    Concrete Unit of Work for the Control Plane (Global Schema).
    Manages transactions exclusively for global configuration and routing tables.
    Collaborating repositories are injected via Ports from the Composition Root.
    """

    as2_partners: AS2TradingPartnerRepositoryPort
    as2_partnerships: AS2PartnershipRepositoryPort
    inbound_routes: InboundRouteRepositoryPort
    outbound_routes: OutboundRouteRepositoryPort
    sftp_partners: SFTPPartnerRepositoryPort
    tenants: TenantRepositoryPort
    edi_headers: EdiHeaderRepositoryPort
    control_plane_outbox: ControlPlaneOutboxRepositoryPort
    settings: SettingsRepositoryPort
    webhooks: WebhookRepositoryPort

    def __init__(
        self,
        global_session: AsyncSession,
        *,
        as2_partners: AS2TradingPartnerRepositoryPort,
        as2_partnerships: AS2PartnershipRepositoryPort,
        inbound_routes: InboundRouteRepositoryPort,
        outbound_routes: OutboundRouteRepositoryPort,
        sftp_partners: SFTPPartnerRepositoryPort,
        tenants: TenantRepositoryPort,
        edi_headers: EdiHeaderRepositoryPort,
        control_plane_outbox: ControlPlaneOutboxRepositoryPort,
        settings: SettingsRepositoryPort,
        webhooks: WebhookRepositoryPort,
    ) -> None:
        super().__init__(global_session)
        self.global_session = global_session
        self.as2_partners = as2_partners
        self.as2_partnerships = as2_partnerships
        self.inbound_routes = inbound_routes
        self.outbound_routes = outbound_routes
        self.sftp_partners = sftp_partners
        self.tenants = tenants
        self.edi_headers = edi_headers
        self.control_plane_outbox = control_plane_outbox
        self.settings = settings
        self.webhooks = webhooks
