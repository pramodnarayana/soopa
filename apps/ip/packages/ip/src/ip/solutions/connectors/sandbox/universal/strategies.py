"""Enterprise Strategy Protocols, Enums, and Boundary DTOs for the Universal Schema Simulator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.connector_port import RecordEnvelopeDTO
from ip.solutions.connectors.sandbox.universal.spec import (
    PullExtractionMode,
    PushCadenceMode,
    SimulatorStreamSpec,
)
from seedwork.domain.types import JsonValue


@dataclass(frozen=True)
class CadenceState:
    """Runtime telemetry tracking progress across push emission cycles."""

    cycle_index: int
    elapsed_seconds: float
    total_emitted: int
    last_emitted_at: datetime


@dataclass(frozen=True)
class ExtractionQuery:
    """Domain query model encapsulating extraction parameters for any simulated stream."""

    stream_name: str
    mode: PullExtractionMode = PullExtractionMode.BOUNDED_TIME_WINDOW
    start_time: datetime | None = None
    end_time: datetime | None = None
    cursor: str | None = None
    offset: int | None = None
    limit: int = 100
    token: str | None = None
    since_version: int | None = None
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class PaginatedSliceDTO:
    """Standardized immutable response envelope returned by all pull extraction strategies."""

    records: Sequence[RecordEnvelopeDTO]
    next_cursor: str | None
    next_offset: int | None
    continuation_token: str | None
    has_more: bool
    total_estimated: int | None = None


class PushCadenceStrategy(Protocol):
    """Protocol encapsulating emission timing and batch sizing for outbound push pipelines."""

    def compute_next_delay_seconds(self, state: CadenceState) -> float:
        """Calculates seconds to wait before triggering the next push cycle."""
        ...

    def compute_batch_size(self, state: CadenceState) -> int:
        """Calculates how many records to synthesize and emit in the current cycle."""
        ...

    def should_emit(self, state: CadenceState) -> bool:
        """Determines whether records should be emitted in the current cycle."""
        ...


class PullExtractionStrategy(Protocol):
    """Protocol encapsulating deterministic slice extraction for simulated stream pulls."""

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        """Extracts a slice of virtual records matching `query` constraints."""
        ...


__all__ = [
    "CadenceState",
    "ExtractionQuery",
    "PaginatedSliceDTO",
    "PullExtractionMode",
    "PullExtractionStrategy",
    "PushCadenceMode",
    "PushCadenceStrategy",
]
