"""Trace specifications and workflow outbox staging helper for IP Data Plane."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.data_plane.mappers import trace_event_to_domain
from ip.engine.adapters.outbound.database.models.data_plane import (
    BatchManifestModel,
    InboundRecordModel,
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
    NormalizedRecordModel,
    OutboundRecordModel,
)
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.intervals.enums import BatchManifestStatus
from ip.engine.domain.trace import IpTraceStatus, map_outbound_status_to_trace_status
from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import case
from sqlalchemy.ext.asyncio import AsyncSession
from strace.domain import TraceEvent, TraceStageAttemptRow
from strace.orm import TraceEventSpec, TraceStageSpec, TraceStageSpecPort


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
    return IpTraceStatus.INGESTED


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
            replay_count=0,
            parent_trace_id=None,
            original_trace_id=None,
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
    "stage_workflow_outbox_event",
]
