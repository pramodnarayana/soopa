"""Port for high-speed per-shard outbox claiming and single-query batch completion."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from seedwork.events import EventEnvelope


class ShardOutboxDrainPort(Protocol):
    """Port for high-speed per-shard outbox claiming and single-query batch completion."""

    async def list_shards(self) -> list[tuple[str, str]]: ...

    async def claim_shard_events(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        worker_id: str,
        limit: int,
        lock_lease_ms: int,
    ) -> list[EventEnvelope]: ...

    async def mark_shard_completed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None: ...

    async def mark_shard_failed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
        retry_delay_seconds: int | None = None,
    ) -> list[str]:
        """Marks claimed events as retryable (with backoff) or terminal FAILED; returns terminal FAILED IDs."""
        ...

    async def mark_shard_dead_letter_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        """Immediately transitions claimed events to terminal FAILED status without further retries."""
        ...


__all__ = ["ShardOutboxDrainPort"]
