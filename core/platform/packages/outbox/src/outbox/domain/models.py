"""Pure immutable Domain Value Objects and Results for Outbox emission outcomes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LogicalStreamEmissionResult:
    """First-class outcome of emitting transactional logical outbox messages."""

    emitted_count: int
    high_watermark: int | None


__all__ = ["LogicalStreamEmissionResult"]
