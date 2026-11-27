"""Single-database Drain-Until-Empty Outbox Relay Adapter."""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from outbox.application.outbox_processor_use_case import (
    OutboxBatchResult,
    OutboxProcessorUseCase,
)
from outbox.ports.outbox_relay_port import OutboxRelayPort

logger = structlog.get_logger(__name__)


class OutboxDrainRelay(OutboxRelayPort):
    """
    Inbound Drain-Until-Empty Outbox Relay for single-database Control Plane workers.

    Unifies Control Plane and Data Plane outbox draining under one operational model:
    - Zero PostgreSQL `LISTEN/NOTIFY` connections (100% RDS Proxy / PgBouncer
      transaction-pooling compatible).
    - Zero `NOTIFY` SQL inside business UoWs (eliminates global `AsyncQueueLock`
      commit serialization).
    - Drains pending batches back-to-back with 0ms delay via `FOR UPDATE SKIP LOCKED`
      until empty, then waits with adaptive idle backoff and wakes instantaneously
      on graceful shutdown.
    """

    def __init__(
        self,
        processor: OutboxProcessorUseCase,
        *,
        relay_name: str = "outbox",
        poll_interval_seconds: float = 0.25,
        max_idle_poll_interval_seconds: float = 1.0,
        error_backoff_seconds: float = 5.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be strictly positive")
        if max_idle_poll_interval_seconds < poll_interval_seconds:
            raise ValueError(
                "max_idle_poll_interval_seconds must be greater than or equal to "
                "poll_interval_seconds"
            )
        if error_backoff_seconds <= 0:
            raise ValueError("error_backoff_seconds must be strictly positive")

        self.processor = processor
        self.relay_name = relay_name
        self.poll_interval_seconds = poll_interval_seconds
        self.max_idle_poll_interval_seconds = max_idle_poll_interval_seconds
        self.error_backoff_seconds = error_backoff_seconds
        self.is_running = False
        self._task: asyncio.Task[object] | None = None
        self._stop_event = asyncio.Event()

    def background_tasks(self) -> list[asyncio.Task[object]]:
        return [self._task] if self._task is not None else []

    def start(self) -> None:
        if not self.is_running:
            self._stop_event.clear()
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(
                "outbox_drain_relay_started",
                relay_name=self.relay_name,
                poll_interval_seconds=self.poll_interval_seconds,
                max_idle_poll_interval_seconds=self.max_idle_poll_interval_seconds,
            )

    async def stop(self) -> None:
        self.is_running = False
        self._stop_event.set()
        self.processor.stop()

        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("outbox_drain_relay_stopped", relay_name=self.relay_name)

    async def drain_until_empty(self) -> OutboxBatchResult:
        """Drains pending batches back-to-back with 0ms delay until empty or a publish failure occurs."""
        total_claimed = 0
        total_completed = 0
        total_failed = 0
        has_more = False

        while True:
            if not self.is_running and self._task is not None:
                break
            batch = await self.processor.process_batch()
            total_claimed += batch.claimed_count
            total_completed += batch.completed_count
            total_failed += batch.failed_count
            has_more = batch.has_more

            # Break out of tight 0ms loop on any publish failure to avoid hammering a degraded broker.
            if batch.failed_count > 0 or not batch.has_more:
                break

        return OutboxBatchResult(
            claimed_count=total_claimed,
            completed_count=total_completed,
            failed_count=total_failed,
            has_more=has_more,
        )

    async def _wait_or_stop(self, timeout_seconds: float) -> None:
        if not self.is_running:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout_seconds)

    async def _run_loop(self) -> None:
        idle_interval = self.poll_interval_seconds
        while self.is_running:
            try:
                cycle = await self.drain_until_empty()
                if not self.is_running:
                    break

                if cycle.failed_count > 0 and cycle.completed_count == 0:
                    logger.error(
                        "outbox_drain_relay_batch_failed_backing_off",
                        relay_name=self.relay_name,
                        claimed_count=cycle.claimed_count,
                        failed_count=cycle.failed_count,
                        backoff_seconds=self.error_backoff_seconds,
                    )
                    idle_interval = self.poll_interval_seconds
                    await self._wait_or_stop(self.error_backoff_seconds)
                elif cycle.claimed_count > 0:
                    if cycle.failed_count > 0:
                        logger.error(
                            "outbox_drain_relay_partial_batch_failure",
                            relay_name=self.relay_name,
                            claimed_count=cycle.claimed_count,
                            completed_count=cycle.completed_count,
                            failed_count=cycle.failed_count,
                            has_more=cycle.has_more,
                        )
                    idle_interval = self.poll_interval_seconds
                    await self._wait_or_stop(idle_interval)
                else:
                    await self._wait_or_stop(idle_interval)
                    idle_interval = min(idle_interval * 2.0, self.max_idle_poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox_drain_relay_error", relay_name=self.relay_name)
                idle_interval = self.poll_interval_seconds
                await self._wait_or_stop(self.error_backoff_seconds)


__all__ = ["OutboxDrainRelay"]
