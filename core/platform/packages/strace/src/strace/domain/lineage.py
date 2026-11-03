"""Causal trace lineage protocols, value objects, and aggregation helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from seedwork.domain.types import JsonDict

from strace.domain.enums import TraceStatus


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
    """Single execution attempt summary in a causal lineage tree."""

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
    """Merges stage rows in pipeline order by trace_id."""
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
    "TraceLineageContext",
    "TraceLineageItemDTO",
    "TraceReplayMetadata",
    "TraceStageAttemptRow",
    "aggregate_trace_lineage_attempts",
    "extract_deepest_lineage_context",
]
