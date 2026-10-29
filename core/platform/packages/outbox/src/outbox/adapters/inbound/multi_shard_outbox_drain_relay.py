"""High-speed Drain-Until-Empty multi-shard Outbox relay for high-volume Data Plane shards."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from typing import Protocol

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


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
    ) -> None: ...


class MultiShardOutboxDrainRelay:
    """
    Pillar 3 High-Speed "Drain-Until-Empty" Outbox Relay for multi-shard Data Planes.

    Why this replaces PostgreSQL LISTEN/NOTIFY on high-volume Data Plane shards:
    - Avoids PostgreSQL's global `AsyncQueueLock` serialization during `PreCommit_Notify()`.
    - Claims up to `batch_size` (default 500) events per shard ordered by `lane DESC, created_at ASC`
      using `FOR UPDATE SKIP LOCKED` with 0s artificial delay.
    - Loops immediately with `0ms` sleep while a shard has pending events until 100% drained.
    - Marks all published events `PROCESSED` in 1 single SQL statement (`WHERE id IN (:ids)`).
    """

    def __init__(
        self,
        repository: ShardOutboxDrainPort,
        publisher: OutboxPublisherPort,
        *,
        batch_size: int = 500,
        shard_concurrency: int = 5,
        lock_lease_ms: int = 30000,
        poll_interval_seconds: float = 0.2,
        worker_id: str | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be strictly positive")
        if shard_concurrency <= 0:
            raise ValueError("shard_concurrency must be strictly positive")
        self.repository = repository
        self.publisher = publisher
        self.batch_size = batch_size
        self.shard_concurrency = shard_concurrency
        self.lock_lease_ms = lock_lease_ms
        self.poll_interval_seconds = poll_interval_seconds
        self.worker_id = worker_id or generate_id(SystemIdPrefix.GENERIC)
        self.is_running = False
        self._task: asyncio.Task[None] | None = None

    def background_tasks(self) -> list[asyncio.Task[None]]:
        return [self._task] if self._task is not None else []

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(
                "multi_shard_outbox_drain_relay_started",
                worker_id=self.worker_id,
                batch_size=self.batch_size,
                shard_concurrency=self.shard_concurrency,
                poll_interval_seconds=self.poll_interval_seconds,
            )

    async def stop(self) -> None:
        self.is_running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("multi_shard_outbox_drain_relay_stopped", worker_id=self.worker_id)

    async def drain_shard_until_empty(self, shard_name: str, shard_dsn: str) -> int:
        """Drains a single shard in a tight 0ms loop until no pending events remain."""
        total_published = 0
        while True:
            events = await self.repository.claim_shard_events(
                shard_name=shard_name,
                shard_dsn=shard_dsn,
                worker_id=self.worker_id,
                limit=self.batch_size,
                lock_lease_ms=self.lock_lease_ms,
            )
            if not events:
                break

            batch_failure_reason: str | None = None
            try:
                successful_ids = await self.publisher.publish_batch(events)
            except Exception as exc:
                logger.exception(
                    "shard_outbox_batch_publish_failed",
                    shard_name=shard_name,
                    worker_id=self.worker_id,
                    error=str(exc),
                )
                successful_ids = []
                batch_failure_reason = str(exc) or type(exc).__name__

            successful_set = set(successful_ids)
            completed_ids = [e.id for e in events if e.id in successful_set]
            failed_ids = [e.id for e in events if e.id not in successful_set]

            if completed_ids:
                await self.repository.mark_shard_completed_batch(
                    shard_name=shard_name,
                    shard_dsn=shard_dsn,
                    event_ids=completed_ids,
                    worker_id=self.worker_id,
                )
                total_published += len(completed_ids)
                logger.info(
                    "shard_outbox_batch_drained",
                    shard_name=shard_name,
                    worker_id=self.worker_id,
                    completed_count=len(completed_ids),
                    total_drained_in_cycle=total_published,
                )

            if failed_ids:
                reason = batch_failure_reason or "Event was not acknowledged by batch publisher"
                await self.repository.mark_shard_failed_batch(
                    shard_name=shard_name,
                    shard_dsn=shard_dsn,
                    event_ids=failed_ids,
                    worker_id=self.worker_id,
                    error_message=reason,
                )
                logger.error(
                    "shard_outbox_batch_marked_failed",
                    shard_name=shard_name,
                    worker_id=self.worker_id,
                    failed_count=len(failed_ids),
                    reason=reason,
                )
                # Break tight loop on transport failure so we back off before retrying
                break

            if not self.is_running and self._task is not None:
                break

        return total_published

    async def drain_all_shards_once(self) -> int:
        """Drains all registered shards concurrently (bounded by shard_concurrency)."""
        shards = await self.repository.list_shards()
        if not shards:
            return 0

        semaphore = asyncio.Semaphore(self.shard_concurrency)

        async def _bounded_drain(shard_name: str, shard_dsn: str) -> int:
            async with semaphore:
                return await self.drain_shard_until_empty(shard_name, shard_dsn)

        counts = await asyncio.gather(
            *[_bounded_drain(shard_name, shard_dsn) for shard_name, shard_dsn in shards],
            return_exceptions=True,
        )
        total = 0
        for count in counts:
            if isinstance(count, Exception):
                logger.error("shard_outbox_drain_error", error=str(count))
            elif isinstance(count, int):
                total += count
        return total

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                published = await self.drain_all_shards_once()
                if published == 0 and self.is_running:
                    await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "multi_shard_outbox_drain_relay_loop_error",
                    worker_id=self.worker_id,
                )
                await asyncio.sleep(1.0)


__all__ = ["MultiShardOutboxDrainRelay", "ShardOutboxDrainPort"]
