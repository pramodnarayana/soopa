import structlog
from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.types import TenantSession
from database.uow import BaseSqlAlchemyUnitOfWork
from edi.adapters.outbound.database.api_gateway_repository import SqlAlchemyApiGatewayRepository
from edi.adapters.outbound.database.data_plane.as2_partner_repository import (
    SqlAlchemyDataPlaneAS2PartnerRepository,
)
from edi.adapters.outbound.database.data_plane.as2_partnership_repository import (
    SqlAlchemyDataPlaneAS2PartnershipRepository,
)
from edi.adapters.outbound.database.data_plane.edi_header_repository import (
    SqlAlchemyDataPlaneEdiHeaderRepository,
)
from edi.adapters.outbound.database.data_plane.inbound_route_repository import (
    SqlAlchemyDataPlaneInboundRouteRepository,
)
from edi.adapters.outbound.database.data_plane.outbound_route_repository import (
    SqlAlchemyDataPlaneOutboundRouteRepository,
)
from edi.adapters.outbound.database.data_plane.outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)
from edi.adapters.outbound.database.data_plane.sftp_partner_repository import (
    SqlAlchemyDataPlaneSFTPPartnerRepository,
)
from edi.adapters.outbound.database.data_plane.webhook_repository import (
    SqlAlchemyDataPlaneWebhookRepository,
)
from edi.adapters.outbound.database.models.data_plane import ProcessedEvent
from edi.adapters.outbound.database.trace_repository import SqlAlchemyTraceRepository
from edi.adapters.outbound.database.transaction_repository import SqlAlchemyTransactionRepository
from edi.ports.outbound.api_gateway_repository import ApiGatewayRepositoryPort
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

    def __init__(
        self,
        tenant_session: AsyncSession,
        storage: StoragePort,
    ) -> None:
        super().__init__(tenant_session)
        self._storage = storage
        self.api_gateway_transactions = SqlAlchemyApiGatewayRepository(tenant_session)
        self.transactions = SqlAlchemyTransactionRepository(TenantSession(tenant_session), storage)
        self.traces = SqlAlchemyTraceRepository(tenant_session, storage)
        self.outbox = SqlAlchemyDataPlaneOutboxRepository(session=tenant_session)
        self.inbound_routes = SqlAlchemyDataPlaneInboundRouteRepository(session=tenant_session)
        self.outbound_routes = SqlAlchemyDataPlaneOutboundRouteRepository(session=tenant_session)
        self.sftp_partners = SqlAlchemyDataPlaneSFTPPartnerRepository(session=tenant_session)
        self.as2_partners = SqlAlchemyDataPlaneAS2PartnerRepository(session=tenant_session)
        self.as2_partnerships = SqlAlchemyDataPlaneAS2PartnershipRepository(session=tenant_session)
        self.webhooks = SqlAlchemyDataPlaneWebhookRepository(session=tenant_session)
        self.edi_headers = SqlAlchemyDataPlaneEdiHeaderRepository(session=tenant_session)

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        """
        Attempts to insert an idempotency record into the events_processed table.
        Returns True if successful (meaning the event is new).
        Returns False if a unique constraint violation occurs (meaning the event was already processed).
        This executes within the UoW's active transaction but does NOT commit.
        """
        if not tenant_id or not idempotency_key:
            return True

        stmt = (
            insert(ProcessedEvent)
            .values(tenant_id=tenant_id, idempotency_key=idempotency_key)
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        )
        result = await self.session.execute(stmt)
        return type(result) is CursorResult and result.rowcount > 0
