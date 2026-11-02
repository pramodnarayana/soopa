"""Trace specifications and workflow outbox staging helper for IP Data Plane."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.data_plane.mappers import trace_event_to_domain
from ip.engine.adapters.outbound.database.models.data_plane import (
    InboundRecordModel,
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
    NormalizedRecordModel,
    OutboundRecordModel,
)
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.trace import IpTraceStatus
from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession
from strace.domain import TraceEvent, TraceStageAttemptRow
from strace.orm import TraceEventSpec, TraceStageSpec, TraceStageSpecPort

from database.outbox_serializer import serialize_domain_event


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
        status_col=OutboundRecordModel.status,
        correlation_cols=(OutboundRecordModel.correlation_id,),
        to_attempt_row=lambda out: TraceStageAttemptRow(
            trace_id=out.trace_id,
            correlation_id=out.correlation_id,
            status=IpTraceStatus(out.status),
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


def build_ip_outbox_record_from_envelope(envelope: EventEnvelope) -> IpDataPlaneOutboxRecord:
    """Builds an IpDataPlaneOutboxRecord for staging an EventEnvelope."""
    now = datetime.now(UTC)
    return IpDataPlaneOutboxRecord(
        id=generate_id(IpIdPrefix.OUTBOX.value),
        tenant_id=envelope.tenant_id or "",
        idempotency_key=envelope.idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY.value),
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


__all__ = [
    "IP_TRACE_EVENT_SPEC",
    "IP_TRACE_STAGE_SPECS",
    "build_ip_outbox_record_from_envelope",
    "stage_workflow_outbox_event",
]
