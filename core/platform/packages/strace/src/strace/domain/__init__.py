"""Domain layer exports for the Soopa platform trace package."""

from __future__ import annotations

from strace.domain.enums import TraceEventType, TraceStatus
from strace.domain.models import (
    HasTraceLineageFields,
    TracedAggregateRoot,
    TraceErrorDetails,
    TraceEvent,
    TraceLineageContext,
    TraceLineageItemDTO,
    TraceReplayMetadata,
    TraceStageAttemptRow,
    aggregate_trace_lineage_attempts,
    extract_deepest_lineage_context,
)

__all__ = [
    "HasTraceLineageFields",
    "TraceErrorDetails",
    "TraceEvent",
    "TraceEventType",
    "TraceLineageContext",
    "TraceLineageItemDTO",
    "TraceReplayMetadata",
    "TraceStageAttemptRow",
    "TraceStatus",
    "TracedAggregateRoot",
    "aggregate_trace_lineage_attempts",
    "extract_deepest_lineage_context",
]
