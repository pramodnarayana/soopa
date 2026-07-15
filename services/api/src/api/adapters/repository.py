from api.adapters.api_token_repository import SqlAlchemyApiTokenRepository
from api.adapters.as2_partner_repository import SqlAlchemyAS2TradingPartnerRepository
from api.adapters.as2_partnership_repository import SqlAlchemyAS2PartnershipRepository
from api.adapters.edi_header_repository import SqlAlchemyEdiHeaderRepository
from api.adapters.inbound_route_repository import SqlAlchemyInboundRouteRepository
from api.adapters.outbound_route_repository import SqlAlchemyOutboundRouteRepository
from api.adapters.outbox_repository import SqlAlchemyOutboxRepository
from api.adapters.sftp_repository import SqlAlchemySFTPPartnerRepository
from api.adapters.tenant_repository import SqlAlchemyTenantRepository
from api.adapters.transaction_repository import SqlAlchemyTransactionRepository
from api.adapters.webhook_repository import SqlAlchemyWebhookRepository
from api.ports.repository import ControlPlaneRepositoryPort, DataPlaneRepositoryPort
from database.base_repository import GlobalSession, TenantSession


class SqlAlchemyControlPlaneRepository(
    ControlPlaneRepositoryPort,
    SqlAlchemyAS2TradingPartnerRepository,
    SqlAlchemyAS2PartnershipRepository,
    SqlAlchemyInboundRouteRepository,
    SqlAlchemyOutboundRouteRepository,
    SqlAlchemySFTPPartnerRepository,
    SqlAlchemyWebhookRepository,
    SqlAlchemyEdiHeaderRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyApiTokenRepository,
    SqlAlchemyOutboxRepository,
):
    def __init__(self, session: GlobalSession) -> None:
        self.session = session
        SqlAlchemyAS2TradingPartnerRepository.__init__(self, session)
        SqlAlchemyAS2PartnershipRepository.__init__(self, session)
        SqlAlchemyInboundRouteRepository.__init__(self, session)
        SqlAlchemyOutboundRouteRepository.__init__(self, session)
        SqlAlchemySFTPPartnerRepository.__init__(self, session)
        SqlAlchemyWebhookRepository.__init__(self, session)
        SqlAlchemyEdiHeaderRepository.__init__(self, session)
        SqlAlchemyTenantRepository.__init__(self, session)
        SqlAlchemyOutboxRepository.__init__(self, session)
        SqlAlchemyApiTokenRepository.__init__(self, session)


class SqlAlchemyDataPlaneRepository(DataPlaneRepositoryPort, SqlAlchemyTransactionRepository):
    def __init__(self, session: TenantSession) -> None:
        self.session = session
        SqlAlchemyTransactionRepository.__init__(self, session)
