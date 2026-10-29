"""SQLAlchemy Unit of Work implementation for Integration Platform Data Plane."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.mappers import (
    trace_event_to_domain,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_ledger_repository import (
    SqlAlchemyNormalizationLedgerRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_rejection_repository import (
    SqlAlchemyNormalizationRejectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalized_record_repository import (
    SqlAlchemyNormalizedRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.pending_reference_repository import (
    SqlAlchemyPendingReferenceRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_rejection_repository import (
    SqlAlchemyReplicaRejectionRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    InboundRecordModel,
    IpDataPlaneOutboxRecord,
    IpProcessedEventModel,
    IpTraceEventModel,
    NormalizedRecordModel,
    OutboundRecordModel,
)
from ip.engine.domain.enums import PipelineLayer
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from strace.adapters import (
    SqlAlchemyTraceRepository,
    TraceEventSpec,
    TraceStageSpec,
    TraceStageSpecPort,
)
from strace.domain import TraceEvent, TraceStageAttemptRow, TraceStatus
from strace.ports import TraceRepositoryPort

from database.outbox_serializer import serialize_domain_event
from database.uow import BaseSqlAlchemyUnitOfWork


def _ip_trace_event_to_orm(event: TraceEvent) -> IpTraceEventModel:
    return IpTraceEventModel(
        id=event.id,
        tenant_id=event.tenant_id,
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        event_type=event.event_type,
        actor=event.actor,
        metadata_=dict(event.metadata) if event.metadata is not None else None,
        created_at=event.created_at,
    )


IP_TRACE_EVENT_SPEC: TraceEventSpec[IpTraceEventModel] = TraceEventSpec(
    model_cls=IpTraceEventModel,
    to_domain_fn=trace_event_to_domain,
    to_orm_fn=_ip_trace_event_to_orm,
)

IP_TRACE_STAGE_SPECS: tuple[TraceStageSpecPort, ...] = (
    TraceStageSpec(
        model_cls=InboundRecordModel,
        timestamp_col=InboundRecordModel.received_at,
        static_status=TraceStatus.INGESTED,
        correlation_cols=(InboundRecordModel.correlation_id,),
        to_attempt_row=lambda inb: TraceStageAttemptRow(
            trace_id=inb.trace_id,
            correlation_id=inb.correlation_id,
            status=TraceStatus.INGESTED,
            primary_layer=PipelineLayer.L1_INGEST,
            created_at=inb.received_at,
            replay_count=inb.replay_count,
            parent_trace_id=inb.parent_trace_id,
            original_trace_id=inb.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=NormalizedRecordModel,
        timestamp_col=NormalizedRecordModel.normalized_at,
        static_status=TraceStatus.NORMALIZED,
        correlation_cols=(NormalizedRecordModel.correlation_id,),
        to_attempt_row=lambda nrm: TraceStageAttemptRow(
            trace_id=nrm.trace_id,
            correlation_id=nrm.correlation_id,
            status=TraceStatus.NORMALIZED,
            primary_layer=PipelineLayer.L3_NORMALIZE,
            created_at=nrm.normalized_at,
            replay_count=nrm.replay_count,
            parent_trace_id=nrm.parent_trace_id,
            original_trace_id=nrm.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=OutboundRecordModel,
        timestamp_col=OutboundRecordModel.sent_at,
        status_col=OutboundRecordModel.status,
        correlation_cols=(OutboundRecordModel.correlation_id,),
        to_attempt_row=lambda out: TraceStageAttemptRow(
            trace_id=out.trace_id,
            correlation_id=out.correlation_id,
            status=TraceStatus(out.status),
            primary_layer=PipelineLayer.L5_DELIVER,
            created_at=out.sent_at,
            replay_count=out.replay_count,
            parent_trace_id=out.parent_trace_id,
            original_trace_id=out.original_trace_id,
        ),
    ),
)


class SqlAlchemyIpDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork, IpDataPlaneUnitOfWorkPort):
    """Concrete Unit of Work for the Integration Platform Data Plane (tenant shards)."""

    inbound_records: InboundRecordRepositoryPort
    replica_records: ReplicaRecordRepositoryPort
    replica_rejections: ReplicaRejectionRepositoryPort
    normalized_records: NormalizedRecordRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort
    normalization_ledger: NormalizationLedgerRepositoryPort
    normalization_rejections: NormalizationRejectionRepositoryPort
    pending_references: PendingReferenceRepositoryPort
    traces: TraceRepositoryPort

    def __init__(
        self,
        tenant_session: AsyncSession,
        storage: TieredStoragePort | None = None,
    ) -> None:
        super().__init__(tenant_session)
        self.tenant_session = tenant_session
        self.inbound_records = SqlAlchemyInboundRecordRepository(tenant_session, storage=storage)
        self.replica_records = SqlAlchemyReplicaRecordRepository(tenant_session)
        self.replica_rejections = SqlAlchemyReplicaRejectionRepository(tenant_session)
        self.normalized_records = SqlAlchemyNormalizedRecordRepository(tenant_session)
        self.entity_maps = SqlAlchemyGlobalEntityMapRepository(tenant_session)
        self.outbound_records = SqlAlchemyOutboundRecordRepository(tenant_session, storage=storage)
        self.normalization_ledger = SqlAlchemyNormalizationLedgerRepository(tenant_session)
        self.normalization_rejections = SqlAlchemyNormalizationRejectionRepository(tenant_session)
        self.pending_references = SqlAlchemyPendingReferenceRepository(tenant_session)
        self.traces = SqlAlchemyTraceRepository(
            tenant_session,
            event_spec=IP_TRACE_EVENT_SPEC,
            stage_specs=IP_TRACE_STAGE_SPECS,
        )

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        """Atomically claims an inbound event idempotency key in ip_processed_events."""
        stmt = (
            pg_insert(IpProcessedEventModel)
            .values(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
            )
            .on_conflict_do_nothing(index_elements=[IpProcessedEventModel.idempotency_key])
            .returning(IpProcessedEventModel.idempotency_key)
        )
        result = await self.tenant_session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        """Releases a previously claimed idempotency key when a chunk fails transiently (NACK)."""
        stmt = delete(IpProcessedEventModel).where(
            IpProcessedEventModel.idempotency_key == idempotency_key,
            IpProcessedEventModel.tenant_id == tenant_id,
        )
        await self.tenant_session.execute(stmt)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        """Stages an EventEnvelope into `public.ip_outbox` within the current shard transaction."""
        now = datetime.now(UTC)
        self.tenant_session.add(
            IpDataPlaneOutboxRecord(
                id=generate_id(DomainIdPrefix.IP_OUTBOX.value),
                tenant_id=envelope.tenant_id or "",
                idempotency_key=envelope.idempotency_key
                or generate_id(SystemIdPrefix.IDEMPOTENCY.value),
                event_type=envelope.event_type,
                trace_id=envelope.trace_id,
                correlation_id=envelope.correlation_id,
                lane=envelope.lane.value,
                payload=serialize_domain_event(envelope),
                status=OutboxStatus.PENDING.value,
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        )
        await self.tenant_session.flush()


def stage_workflow_outbox_event(
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    idempotency_key: str | None,
    payload: JsonDict,
) -> None:
    """Stages a workflow domain event into `public.ip_outbox` within the same shard transaction."""
    now = datetime.now(UTC)
    trace_id_raw = payload.get("trace_id")
    corr_id_raw = payload.get("correlation_id")
    session.add(
        IpDataPlaneOutboxRecord(
            id=generate_id(DomainIdPrefix.IP_OUTBOX.value),
            tenant_id=tenant_id,
            idempotency_key=idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY.value),
            event_type=event_type,
            trace_id=str(trace_id_raw) if isinstance(trace_id_raw, str) and trace_id_raw else None,
            correlation_id=(
                str(corr_id_raw) if isinstance(corr_id_raw, str) and corr_id_raw else None
            ),
            lane=EventProcessingLane.REALTIME.value,
            payload=dict(payload),
            status=OutboxStatus.PENDING.value,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
    )


__all__ = [
    "IP_TRACE_EVENT_SPEC",
    "IP_TRACE_STAGE_SPECS",
    "SqlAlchemyIpDataPlaneUnitOfWork",
    "stage_workflow_outbox_event",
]
