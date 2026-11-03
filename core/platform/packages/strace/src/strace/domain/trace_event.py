"""Core TraceEvent value objects and TracedAggregateRoot base class."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict


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
        return self._trace_events

    def add_trace_event(self, event: TraceEvent) -> None:
        self._trace_events.append(event)

    def clear_trace_events(self) -> None:
        self._trace_events.clear()


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


__all__ = [
    "TraceErrorDetails",
    "TraceEvent",
    "TracedAggregateRoot",
]
