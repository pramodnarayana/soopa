"""Trace specifications and workflow outbox staging helper for IP Data Plane."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from ip.engine.adapters.outbound.database.data_plane.mappers import trace_event_to_domain
from ip.engine.adapters.outbound.database.models.data_plane import (
    BatchManifestModel,
    InboundRecordModel,
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
    NormalizedRecordModel,
    OutboundRecordModel,
    ReplicaRecordModel,
)
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.intervals.enums import BatchManifestStatus
from ip.engine.domain.trace import IpTraceStatus, map_outbound_status_to_trace_status
from orchestration.adapters.outbound.database.models import WorkflowRunModel
from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import SQLColumnExpression, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from strace.domain import TraceEvent, TraceStageAttemptRow, TraceStatus
from strace.orm import (
    TenantTraceLineageOrmModel,
    TraceEventSpec,
    TraceStageSpec,
    TraceStageSpecPort,
)


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

_OUTBOUND_TRACE_STATUS_COL = case(
    (
        OutboundRecordModel.status == OutboundDispatchStatus.IN_FLIGHT.value,
        IpTraceStatus.PENDING.value,
    ),
    (
        OutboundRecordModel.status == OutboundDispatchStatus.RATE_LIMITED.value,
        IpTraceStatus.RETRY_SCHEDULED.value,
    ),
    else_=OutboundRecordModel.status,
)

_MANIFEST_TRACE_STATUS_COL = case(
    (
        BatchManifestModel.status == BatchManifestStatus.PROCESSING.value,
        IpTraceStatus.PENDING.value,
    ),
    (
        BatchManifestModel.status == BatchManifestStatus.COMPLETED.value,
        IpTraceStatus.PROCESSED.value,
    ),
    (
        BatchManifestModel.status == BatchManifestStatus.FAILED.value,
        IpTraceStatus.FAILED.value,
    ),
    (
        BatchManifestModel.status == BatchManifestStatus.QUARANTINED.value,
        IpTraceStatus.DEAD_LETTERED.value,
    ),
    (
        BatchManifestModel.status == BatchManifestStatus.INGESTED.value,
        IpTraceStatus.INGESTED.value,
    ),
    else_=IpTraceStatus.INGESTED.value,
)


def map_manifest_status_to_trace_status(status: BatchManifestStatus | str) -> IpTraceStatus:
    resolved = status if isinstance(status, BatchManifestStatus) else BatchManifestStatus(status)
    if resolved is BatchManifestStatus.PROCESSING:
        return IpTraceStatus.PENDING
    if resolved is BatchManifestStatus.COMPLETED:
        return IpTraceStatus.PROCESSED
    if resolved is BatchManifestStatus.FAILED:
        return IpTraceStatus.FAILED
    if resolved is BatchManifestStatus.QUARANTINED:
        return IpTraceStatus.DEAD_LETTERED
    return IpTraceStatus.INGESTED


def map_workflow_status_to_trace_status(status: str) -> IpTraceStatus:
    """Maps a WorkflowRun status token to its corresponding IpTraceStatus."""
    if status in ("QUEUED", "RUNNING", "WAITING"):
        return IpTraceStatus.PENDING
    if status == "SUCCEEDED":
        return IpTraceStatus.PROCESSED
    if status in ("FAILED", "CANCELLED"):
        return IpTraceStatus.FAILED
    return IpTraceStatus.UNKNOWN


@dataclass(frozen=True, kw_only=True)
class WorkflowTraceStageSpec(TraceStageSpecPort):
    """Custom TraceStageSpecPort implementation for durable workflow runs."""

    model_cls: type[WorkflowRunModel]
    timestamp_col: InstrumentedAttribute[datetime]
    to_attempt_row: Callable[[WorkflowRunModel], TraceStageAttemptRow]
    correlation_cols: tuple[InstrumentedAttribute[str | None], ...] = ()
    status_col: SQLColumnExpression[str] | None = None
    static_status: TraceStatus | str | None = None

    def get_model_cls(self) -> type[TenantTraceLineageOrmModel]:
        return cast(type[TenantTraceLineageOrmModel], self.model_cls)

    async def fetch_lineage_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        root_trace_id: str,
    ) -> list[TraceStageAttemptRow]:
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                or_(
                    self.model_cls.trace_id == root_trace_id,
                    self.model_cls.original_trace_id == root_trace_id,
                ),
            )
            .order_by(self.timestamp_col.asc())
        )
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]

    async def fetch_attempts_for_trace_ids(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_ids: Sequence[str],
    ) -> list[TraceStageAttemptRow]:
        if not trace_ids:
            return []
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                self.model_cls.trace_id.in_(trace_ids),
            )
            .order_by(self.timestamp_col.asc())
        )
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]

    async def find_correlation_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        correlation_id: str,
        limit: int,
    ) -> list[TraceStageAttemptRow]:
        if not self.correlation_cols:
            return []
        corr_predicate = or_(*(col == correlation_id for col in self.correlation_cols))
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                corr_predicate,
            )
            .order_by(self.timestamp_col.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]

    async def list_recent_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        limit: int,
        status: TraceStatus | str | None = None,
        min_replay_count: int | None = None,
        downstream_models: Sequence[type[TenantTraceLineageOrmModel]] = (),
    ) -> list[TraceStageAttemptRow]:
        stmt = select(self.model_cls).where(self.model_cls.tenant_id == tenant_id)
        if min_replay_count is not None:
            stmt = stmt.where(self.model_cls.replay_count >= min_replay_count)
        if status is not None and self.status_col is not None:
            status_val = status.value if hasattr(status, "value") else str(status)
            stmt = stmt.where(self.status_col == status_val)
        stmt = stmt.order_by(self.timestamp_col.desc()).limit(limit)
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]


def build_workflow_trace_stage_spec(
    workflow_run_model_cls: type[WorkflowRunModel],
) -> TraceStageSpecPort:
    """Builds a declarative TraceStageSpecPort for durable workflow runs."""
    status_col = case(
        (
            workflow_run_model_cls.status.in_(("QUEUED", "RUNNING", "WAITING")),
            IpTraceStatus.PENDING.value,
        ),
        (workflow_run_model_cls.status == "SUCCEEDED", IpTraceStatus.PROCESSED.value),
        (
            workflow_run_model_cls.status.in_(("FAILED", "CANCELLED")),
            IpTraceStatus.FAILED.value,
        ),
        else_=IpTraceStatus.UNKNOWN.value,
    )
    correlation_col = getattr(workflow_run_model_cls, "correlation_id", None)
    corr_cols = (correlation_col,) if correlation_col is not None else ()
    return WorkflowTraceStageSpec(
        model_cls=workflow_run_model_cls,
        timestamp_col=workflow_run_model_cls.created_at,
        status_col=status_col,
        correlation_cols=corr_cols,
        to_attempt_row=lambda wf: TraceStageAttemptRow(
            trace_id=wf.trace_id,
            correlation_id=getattr(wf, "correlation_id", None),
            status=map_workflow_status_to_trace_status(wf.status),
            primary_layer=PipelineStage.HYDRATE,
            created_at=wf.created_at,
            replay_count=getattr(wf, "replay_count", 0),
            parent_trace_id=getattr(wf, "parent_trace_id", None),
            original_trace_id=getattr(wf, "original_trace_id", None),
        ),
    )


IP_TRACE_STAGE_SPECS: tuple[TraceStageSpecPort, ...] = (
    TraceStageSpec(
        model_cls=BatchManifestModel,
        timestamp_col=BatchManifestModel.created_at,
        status_col=_MANIFEST_TRACE_STATUS_COL,
        correlation_cols=(BatchManifestModel.correlation_id,),
        to_attempt_row=lambda bch: TraceStageAttemptRow(
            trace_id=bch.trace_id,
            correlation_id=bch.correlation_id,
            status=map_manifest_status_to_trace_status(bch.status),
            primary_layer=PipelineStage.NORMALIZE,
            created_at=bch.created_at,
            replay_count=bch.replay_count,
            parent_trace_id=bch.parent_trace_id,
            original_trace_id=bch.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=InboundRecordModel,
        timestamp_col=InboundRecordModel.received_at,
        static_status=IpTraceStatus.INGESTED,
        correlation_cols=(InboundRecordModel.correlation_id,),
        to_attempt_row=lambda inb: TraceStageAttemptRow(
            trace_id=inb.trace_id,
            correlation_id=inb.correlation_id,
            status=IpTraceStatus.INGESTED,
            primary_layer=PipelineStage.INGEST,
            created_at=inb.received_at,
            replay_count=inb.replay_count,
            parent_trace_id=inb.parent_trace_id,
            original_trace_id=inb.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=ReplicaRecordModel,
        timestamp_col=ReplicaRecordModel.updated_at,
        static_status=IpTraceStatus.INGESTED,
        correlation_cols=(ReplicaRecordModel.correlation_id,),
        to_attempt_row=lambda rep: TraceStageAttemptRow(
            trace_id=rep.trace_id,
            correlation_id=rep.correlation_id,
            status=IpTraceStatus.INGESTED,
            primary_layer=PipelineStage.REPLICA,
            created_at=rep.updated_at,
            replay_count=rep.replay_count,
            parent_trace_id=rep.parent_trace_id,
            original_trace_id=rep.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=NormalizedRecordModel,
        timestamp_col=NormalizedRecordModel.normalized_at,
        static_status=IpTraceStatus.NORMALIZED,
        correlation_cols=(NormalizedRecordModel.correlation_id,),
        to_attempt_row=lambda nrm: TraceStageAttemptRow(
            trace_id=nrm.trace_id,
            correlation_id=nrm.correlation_id,
            status=IpTraceStatus.NORMALIZED,
            primary_layer=PipelineStage.NORMALIZE,
            created_at=nrm.normalized_at,
            replay_count=nrm.replay_count,
            parent_trace_id=nrm.parent_trace_id,
            original_trace_id=nrm.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=OutboundRecordModel,
        timestamp_col=OutboundRecordModel.sent_at,
        status_col=_OUTBOUND_TRACE_STATUS_COL,
        correlation_cols=(OutboundRecordModel.correlation_id,),
        to_attempt_row=lambda out: TraceStageAttemptRow(
            trace_id=out.trace_id,
            correlation_id=out.correlation_id,
            status=map_outbound_status_to_trace_status(out.status),
            primary_layer=PipelineStage.DELIVER,
            created_at=out.sent_at,
            replay_count=out.replay_count,
            parent_trace_id=out.parent_trace_id,
            original_trace_id=out.original_trace_id,
        ),
    ),
)


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
            id=generate_id(IpIdPrefix.OUTBOX.value),
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
    "build_workflow_trace_stage_spec",
    "map_workflow_status_to_trace_status",
    "stage_workflow_outbox_event",
]
