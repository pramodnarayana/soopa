import asyncio
import contextlib
import uuid
from typing import Any

import structlog

from ucp.domain.models.outbox_event import OutboxEvent
from ucp.ports.outbox_publisher import OutboxPublisherPort
from ucp.ports.outbox_repository import OutboxRepositoryPort

logger = structlog.get_logger(__name__)


class ControlPlaneOutboxSweeper:
    """
    Fallback Sweeper worker that polls on a strict cron schedule
    to sweep any stuck or failed events.
    """

    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        poll_interval_seconds: int = 5,
        max_concurrent_events: int = 50,
        lock_lease_ms: int = 30000,
        worker_id: str | None = None,
    ):
        self.repository = repository
        self.publisher = publisher
        self.worker_id = worker_id or str(uuid.uuid4())
        self.poll_interval_seconds = poll_interval_seconds
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.is_running = False
        self._task: asyncio.Task[Any] | None = None
        self._poll_event = asyncio.Event()

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("outbox_sweeper_started", worker_id=self.worker_id)

    async def stop(self) -> None:
        self.is_running = False
        self._poll_event.set()  # Wake up the polling loop to exit

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("outbox_sweeper_stopped", worker_id=self.worker_id)

    async def _run_loop(self) -> None:
        async def _sweep() -> None:
            while self.is_running:
                try:
                    await self.poll()
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("outbox_sweeper_poll_loop_error")

                if self.is_running:
                    self._poll_event.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._poll_event.wait(), timeout=self.poll_interval_seconds
                        )

        try:
            if hasattr(self.publisher, "__aenter__"):
                async with self.publisher:
                    await _sweep()
            else:
                await _sweep()
        except asyncio.CancelledError:
            pass

    async def poll(self) -> None:
        # 1. Sweep stuck events
        swept = await self.repository.sweep_stuck_events(self.lock_lease_ms)
        if swept > 0:
            logger.info("stuck_events_swept", count=swept, target_status="PENDING")

        # 2. Claim next events using SKIP LOCKED
        events = await self.repository.claim_next_events(
            worker_id=self.worker_id,
            limit=self.max_concurrent_events,
            lock_lease_ms=self.lock_lease_ms,
        )

        if events:
            logger.debug("sweeper_events_claimed", worker_id=self.worker_id, count=len(events))

            # 3. Execute concurrently
            tasks = [self.process_event(event) for event in events]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def process_event(self, event: OutboxEvent) -> None:
        try:
            await self.publisher.publish(event)
        except Exception as e:
            logger.exception(
                "outbox_event_publishing_failed_by_sweeper",
                event_id=event.id,
                event_type=event.event_type,
            )
            try:
                await self.repository.mark_failed(event.id, self.worker_id, str(e))
            except Exception:
                logger.exception(
                    "outbox_event_mark_failed_error",
                    event_id=event.id,
                )
            return

        try:
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug(
                "outbox_event_processed_by_sweeper", event_id=event.id, event_type=event.event_type
            )
        except Exception:
            logger.exception(
                "outbox_event_mark_completed_error",
                event_id=event.id,
            )
