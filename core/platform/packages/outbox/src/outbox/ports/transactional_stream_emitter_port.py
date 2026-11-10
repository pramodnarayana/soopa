"""Port for zero-bloat in-transaction outbox stream emission."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from outbox.domain.models import LogicalStreamEmissionResult
from seedwork.events import EventEnvelope


class TransactionalStreamEmitterPort(Protocol):
    """
    Emits `EventEnvelope` batches atomically within the caller's ACID transaction
    without writing heap tuples or triggering MVCC update/autovacuum write amplification.
    """

    async def emit_transactional_batch(
        self,
        envelopes: Sequence[EventEnvelope],
    ) -> LogicalStreamEmissionResult: ...


__all__ = ["TransactionalStreamEmitterPort"]
