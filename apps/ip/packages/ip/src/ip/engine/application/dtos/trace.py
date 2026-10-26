"""Trace, Lineage, and Replay DTOs for the Integration Platform Application Layer."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.domain.enums import ReplayStage
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.ports.types import IpTraceDTO, IpTraceLineageItemDTO


@dataclass(frozen=True, kw_only=True)
class ReplayTransactionResultDTO:
    """Structured result of a single deterministic transaction replay."""

    original_trace_id: str
    parent_trace_id: str
    new_trace_id: str
    stage: ReplayStage
    replay_count: int
    correlation_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class BulkReplayFailureItemDTO:
    """Details of a single trace that could not be replayed during a bulk replay operation."""

    trace_id: str
    error_code: IpErrorCode
    message: str


@dataclass(frozen=True, kw_only=True)
class BulkReplayResultDTO:
    """Structured result of a bulk transaction replay operation."""

    stage: ReplayStage
    replayed_count: int
    succeeded_trace_ids: tuple[str, ...]
    new_trace_ids: tuple[str, ...]
    failed_items: tuple[BulkReplayFailureItemDTO, ...] = ()


__all__ = [
    "BulkReplayFailureItemDTO",
    "BulkReplayResultDTO",
    "IpTraceDTO",
    "IpTraceLineageItemDTO",
    "ReplayTransactionResultDTO",
]
