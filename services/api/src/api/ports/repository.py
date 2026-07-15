from api.ports.api_token_repository import ApiTokenRepositoryPort
from api.ports.as2_partner_repository import AS2TradingPartnerRepositoryPort
from api.ports.as2_partnership_repository import AS2PartnershipRepositoryPort
from api.ports.data_plane_as2_repository import DataPlaneAS2RepositoryPort
from api.ports.edi_header_repository import EdiHeaderRepositoryPort
from api.ports.inbound_route_repository import InboundRouteRepositoryPort
from api.ports.outbound_route_repository import OutboundRouteRepositoryPort
from api.ports.outbox_repository import OutboxRepositoryPort
from api.ports.sftp_repository import SFTPPartnerRepositoryPort
from api.ports.tenant_repository import TenantRepositoryPort
from api.ports.transaction_repository import TransactionRepositoryPort
from api.ports.webhook_repository import WebhookRepositoryPort


class ControlPlaneRepositoryPort(
    AS2TradingPartnerRepositoryPort,
    AS2PartnershipRepositoryPort,
    InboundRouteRepositoryPort,
    OutboundRouteRepositoryPort,
    SFTPPartnerRepositoryPort,
    WebhookRepositoryPort,
    EdiHeaderRepositoryPort,
    TenantRepositoryPort,
    ApiTokenRepositoryPort,
    OutboxRepositoryPort,
):
    pass


class DataPlaneRepositoryPort(DataPlaneAS2RepositoryPort, TransactionRepositoryPort):
    pass
