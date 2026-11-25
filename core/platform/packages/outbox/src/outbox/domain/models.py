"""Pure immutable Domain Value Objects and Results for Outbox emission outcomes."""

from __future__ import annotations

from dataclasses import dataclass

from outbox.domain.constants import BatchPublishDisposition


@dataclass(frozen=True)
class LogicalStreamEmissionResult:
    """First-class outcome of emitting transactional logical outbox messages."""

    emitted_count: int
    high_watermark: int | None


@dataclass(frozen=True)
class BatchPublishOutcome:
    """First-class per-event disposition returned by a `StructuredOutboxPublisherPort`."""

    event_id: str
    disposition: BatchPublishDisposition
    error_message: str | None = None
    retry_delay_seconds: int | None = None


__all__ = ["BatchPublishOutcome", "LogicalStreamEmissionResult"]
