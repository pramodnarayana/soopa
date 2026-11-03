from strace.domain import TraceEvent as DomainTraceEvent
from strace.domain import TraceStageAttemptRow
from strace.orm import TraceEventSpec, TraceStageSpec, TraceStageSpecPort

from edi.adapters.outbound.database.models.data_plane import (
    ApiGateway,
    EdiJson,
    EdiMessage,
    TraceEvent,
)


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
        status_col=EdiMessage.status,
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
        status_col=EdiJson.status,
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
        status_col=ApiGateway.status,
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
