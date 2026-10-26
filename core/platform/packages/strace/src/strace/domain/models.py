"""Pure domain models, DTOs, and lineage aggregation functions for the platform trace package."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from seedwork.domain.types import JsonDict
from seedwork.models import AggregateRoot

from strace.domain.enums import TraceStatus


@dataclass(kw_only=True)
class TraceEvent:
    """Base class for trace events that are appended to a TracedAggregateRoot."""

    id: str
    tenant_id: str
    trace_id: str
    event_type: str
    actor: str
    correlation_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: JsonDict | None = None


@dataclass(kw_only=True, eq=False)
class TracedAggregateRoot(AggregateRoot):
    """Base class for DDD Aggregates that support an immutable audit ledger of trace events and lineage."""

    trace_id: str
    tenant_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    _trace_events: list[TraceEvent] = field(
        default_factory=list, init=False, repr=False, hash=False, compare=False
    )

    @property
    def trace_events(self) -> list[TraceEvent]:
        if not hasattr(self, "_trace_events"):
            self._trace_events = []
        return self._trace_events

    def add_trace_event(self, event: TraceEvent) -> None:
        if not hasattr(self, "_trace_events"):
            self._trace_events = []
        self._trace_events.append(event)

    def clear_trace_events(self) -> None:
        if hasattr(self, "_trace_events"):
            self._trace_events.clear()


class HasTraceLineageFields(Protocol):
    """Structural protocol for any stage entity or ORM model participating in trace lineage."""

    @property
    def trace_id(self) -> str: ...

    @property
    def correlation_id(self) -> str | None: ...

    @property
    def parent_trace_id(self) -> str | None: ...

    @property
    def original_trace_id(self) -> str | None: ...

    @property
    def replay_count(self) -> int: ...


@dataclass(frozen=True, kw_only=True)
class TraceErrorDetails:
    """Structured error context attached to a failed or retried TraceEvent."""

    reason: str | None = None
    detail: str | None = None
    response_status_code: int | None = None
    failure_category: str | None = None
    retry_after_seconds: int | None = None
    next_attempt: int | None = None

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {}
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.response_status_code is not None:
            payload["response_status_code"] = self.response_status_code
        if self.failure_category is not None:
            payload["failure_category"] = self.failure_category
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        if self.next_attempt is not None:
            payload["next_attempt"] = self.next_attempt
        return payload


@dataclass(frozen=True, kw_only=True)
class TraceReplayMetadata:
    """Structured lineage metadata attached to a replay TraceEvent."""

    parent_trace_id: str | None
    original_trace_id: str
    replay_count: int

    def to_dict(self) -> JsonDict:
        return {
            "parent_trace_id": self.parent_trace_id,
            "original_trace_id": self.original_trace_id,
            "replay_count": self.replay_count,
        }


@dataclass(frozen=True, kw_only=True)
class TraceLineageContext:
    """Resolved lineage and correlation identifiers for a trace attempt."""

    parent_trace_id: str | None
    original_trace_id: str
    replay_count: int
    correlation_id: str | None


@dataclass(frozen=True, kw_only=True)
class TraceLineageItemDTO:
    """Single execution attempt summary in a transaction's replay lineage tree."""

    trace_id: str
    correlation_id: str | None = None
    status: TraceStatus | str = TraceStatus.UNKNOWN
    primary_layer: str = ""
    created_at: datetime | str | None = None
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class TraceStageAttemptRow:
    """Normalized stage row projection used to merge multi-stage attempts into a lineage tree."""

    trace_id: str
    correlation_id: str | None = None
    status: TraceStatus | str | None = None
    primary_layer: str = ""
    created_at: datetime | str | None = None
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None


def extract_deepest_lineage_context(
    *,
    trace_id: str,
    stages_deepest_first: Sequence[Sequence[HasTraceLineageFields]],
    fallback_correlation_id: str | None = None,
) -> TraceLineageContext:
    """Extracts parent_trace_id, original_trace_id, replay_count, and correlation_id from the deepest stage."""
    for stage_records in stages_deepest_first:
        if stage_records:
            primary = stage_records[-1]
            return TraceLineageContext(
                parent_trace_id=primary.parent_trace_id,
                original_trace_id=primary.original_trace_id or trace_id,
                replay_count=primary.replay_count,
                correlation_id=primary.correlation_id or fallback_correlation_id,
            )
    return TraceLineageContext(
        parent_trace_id=None,
        original_trace_id=trace_id,
        replay_count=0,
        correlation_id=fallback_correlation_id,
    )


def aggregate_trace_lineage_attempts(
    *,
    stage_batches_in_pipeline_order: Sequence[Sequence[TraceStageAttemptRow]],
    fallback_root_trace_id: str | None = None,
) -> list[TraceLineageItemDTO]:
    """Merges stage rows in pipeline order (e.g. L1 -> L3 -> L5 or Stage 1 -> Stage 2 -> Stage 3) by trace_id."""
    by_trace: dict[str, TraceLineageItemDTO] = {}

    for stage_rows in stage_batches_in_pipeline_order:
        for row in stage_rows:
            existing = by_trace.get(row.trace_id)
            resolved_status: TraceStatus | str = (
                row.status
                if row.status is not None
                else (existing.status if existing is not None else TraceStatus.UNKNOWN)
            )
            resolved_created_at = (
                existing.created_at
                if existing is not None and existing.created_at is not None
                else row.created_at
            )
            by_trace[row.trace_id] = TraceLineageItemDTO(
                trace_id=row.trace_id,
                correlation_id=row.correlation_id
                or (existing.correlation_id if existing else None),
                status=resolved_status,
                primary_layer=row.primary_layer or (existing.primary_layer if existing else ""),
                created_at=resolved_created_at,
                replay_count=row.replay_count,
                parent_trace_id=row.parent_trace_id
                or (existing.parent_trace_id if existing else None),
                original_trace_id=row.original_trace_id
                or (existing.original_trace_id if existing else None)
                or fallback_root_trace_id
                or row.trace_id,
            )

    return list(by_trace.values())


__all__ = [
    "HasTraceLineageFields",
    "TraceErrorDetails",
    "TraceEvent",
    "TraceLineageContext",
    "TraceLineageItemDTO",
    "TraceReplayMetadata",
    "TraceStageAttemptRow",
    "TracedAggregateRoot",
    "aggregate_trace_lineage_attempts",
    "extract_deepest_lineage_context",
]
