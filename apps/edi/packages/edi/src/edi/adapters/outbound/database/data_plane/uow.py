import structlog
from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from strace.adapters import (
    SqlAlchemyTraceRepository,
    TraceEventSpec,
    TraceStageSpec,
    TraceStageSpecPort,
)
from strace.domain import TraceEvent as DomainTraceEvent
from strace.domain import TraceStageAttemptRow
from strace.ports import TraceRepositoryPort

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
from edi.adapters.outbound.database.models.data_plane import (
    ApiGateway,
    EdiJson,
    EdiMessage,
    ProcessedEvent,
    TraceEvent,
)
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
from edi.ports.outbound.transaction_repository import TransactionRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort

logger = structlog.get_logger(__name__)


def _edi_trace_event_to_domain(orm: TraceEvent) -> DomainTraceEvent:
    return DomainTraceEvent(
        id=str(orm.id),
        tenant_id=str(orm.tenant_id),
        trace_id=str(orm.trace_id),
        event_type=str(orm.event_type),
        actor=str(orm.actor),
        metadata=dict(orm.metadata_) if orm.metadata_ is not None else {},
        created_at=orm.created_at,
    )


def _edi_trace_event_to_orm(event: DomainTraceEvent) -> TraceEvent:
    return TraceEvent(
        id=event.id,
        tenant_id=event.tenant_id,
        trace_id=event.trace_id,
        event_type=event.event_type,
        actor=event.actor,
        metadata_=dict(event.metadata) if event.metadata is not None else None,
        created_at=event.created_at,
    )


EDI_TRACE_EVENT_SPEC: TraceEventSpec[TraceEvent] = TraceEventSpec(
    model_cls=TraceEvent,
    to_domain_fn=_edi_trace_event_to_domain,
    to_orm_fn=_edi_trace_event_to_orm,
)

EDI_TRACE_STAGE_SPECS: tuple[TraceStageSpecPort, ...] = (
    TraceStageSpec(
        model_cls=EdiMessage,
        timestamp_col=EdiMessage.created_at,
        correlation_cols=(EdiMessage.interchange_control_no, EdiMessage.message_id),
        to_attempt_row=lambda m: TraceStageAttemptRow(
            trace_id=m.trace_id,
            correlation_id=m.interchange_control_no or m.message_id,
            status=m.status,
            primary_layer="STAGE_1_INGEST",
            created_at=m.created_at,
            replay_count=m.replay_count,
            parent_trace_id=m.parent_trace_id,
            original_trace_id=m.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=EdiJson,
        timestamp_col=EdiJson.created_at,
        to_attempt_row=lambda j: TraceStageAttemptRow(
            trace_id=j.trace_id,
            correlation_id=None,
            status=j.status,
            primary_layer="STAGE_2_TRANSFORM",
            created_at=j.created_at,
            replay_count=j.replay_count,
            parent_trace_id=j.parent_trace_id,
            original_trace_id=j.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=ApiGateway,
        timestamp_col=ApiGateway.created_at,
        to_attempt_row=lambda g: TraceStageAttemptRow(
            trace_id=g.trace_id,
            correlation_id=None,
            status=g.status,
            primary_layer="STAGE_3_DELIVER",
            created_at=g.created_at,
            replay_count=g.replay_count,
            parent_trace_id=g.parent_trace_id,
            original_trace_id=g.original_trace_id,
        ),
    ),
)


class SqlAlchemyDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
    """
    Concrete Unit of Work for the EDI Worker Data Plane.

    Wires the pipeline's RepositoryPort (SqlAlchemyRepositoryAdapter) and the
    DataPlaneOutboxRepositoryPort (SqlAlchemyDataPlaneOutboxRepository) together
    behind a single async context manager to ensure atomic transaction boundaries.
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
        self.traces = SqlAlchemyTraceRepository(
            tenant_session,
            event_spec=EDI_TRACE_EVENT_SPEC,
            stage_specs=EDI_TRACE_STAGE_SPECS,
        )
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

    async def has_been_processed(self, tenant_id: str, idempotency_key: str) -> bool:
        """
        Checks if an idempotency record exists in the events_processed table.
        """
        if not tenant_id or not idempotency_key:
            return False

        stmt = select(ProcessedEvent).where(
            ProcessedEvent.tenant_id == tenant_id,
            ProcessedEvent.idempotency_key == idempotency_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
