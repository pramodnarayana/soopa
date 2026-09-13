import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from database.types import TenantSession
from database.uow import BaseSqlAlchemyUnitOfWork
from edi.adapters.outbound.database.data_plane_config_repositories import (
    SqlAlchemyDataPlaneAS2PartnerRepository,
    SqlAlchemyDataPlaneAS2PartnershipRepository,
    SqlAlchemyDataPlaneEdiHeaderRepository,
    SqlAlchemyDataPlaneInboundRouteRepository,
    SqlAlchemyDataPlaneOutboundRouteRepository,
    SqlAlchemyDataPlaneSFTPPartnerRepository,
    SqlAlchemyDataPlaneWebhookRepository,
)
from edi.adapters.outbound.database.postgres_data_plane_outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)
from edi.adapters.outbound.database.trace_repository import SqlAlchemyTraceRepository
from edi.adapters.outbound.database.transaction_repository import SqlAlchemyTransactionRepository
from edi.config.settings import AppSettings
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.trace_repository import TraceRepositoryPort
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """
    Concrete Unit of Work for the EDI Worker Data Plane.

    Wires the pipeline's RepositoryPort (SqlAlchemyRepositoryAdapter) and the
    DataPlaneOutboxRepositoryPort (SqlAlchemyDataPlaneOutboxRepository) together
    behind a single async context manager to ensure atomic transaction boundaries.

    This satisfies the `pipeline.ports.outbound.data_plane_unit_of_work_port.DataPlaneUnitOfWorkPort` Protocol.
    """

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

    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        storage: StoragePort,
    ) -> None:
        super().__init__(session)
        self._settings = settings
        self._storage = storage
        self.transactions = SqlAlchemyTransactionRepository(TenantSession(session), storage)
        self.traces = SqlAlchemyTraceRepository(session, storage)
        self.outbox = SqlAlchemyDataPlaneOutboxRepository(session=session)
        self.inbound_routes = SqlAlchemyDataPlaneInboundRouteRepository(session=session)
        self.outbound_routes = SqlAlchemyDataPlaneOutboundRouteRepository(session=session)
        self.sftp_partners = SqlAlchemyDataPlaneSFTPPartnerRepository(session=session)
        self.as2_partners = SqlAlchemyDataPlaneAS2PartnerRepository(session=session)
        self.as2_partnerships = SqlAlchemyDataPlaneAS2PartnershipRepository(session=session)
        self.webhooks = SqlAlchemyDataPlaneWebhookRepository(session=session)
        self.edi_headers = SqlAlchemyDataPlaneEdiHeaderRepository(session=session)
