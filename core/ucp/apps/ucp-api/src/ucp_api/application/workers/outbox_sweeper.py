import asyncio
import logging
from typing import Any
import uuid
from ...ports.outbox_repository import OutboxRepositoryPort
from ...ports.outbox_publisher import OutboxPublisherPort
from ucp_models.events import ControlPlaneOutbox


logger = logging.getLogger(__name__)


class ControlPlaneOutboxSweeper:
    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        worker_id: str | None = None,
        poll_interval_seconds: int = 5,
        max_concurrent_events: int = 50,
        lock_lease_ms: int = 300000,
    ):
        self.repository = repository
        self.publisher = publisher
        self.worker_id = worker_id or str(uuid.uuid4())
        self.poll_interval_seconds = poll_interval_seconds
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.is_running = False
        self._task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(f"Started ControlPlaneOutboxSweeper {self.worker_id}")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            await self._task
            logger.info(f"Stopped ControlPlaneOutboxSweeper {self.worker_id}")

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                await self.poll()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in outbox sweeper poll loop: {e}", exc_info=True)

            if self.is_running:
                await asyncio.sleep(self.poll_interval_seconds)

    async def poll(self) -> None:
        # 1. Sweep stuck events
        swept = await self.repository.sweep_stuck_events(self.lock_lease_ms)
        if swept > 0:
            logger.info(f"Swept {swept} stuck outbox events back to PENDING.")

        # 2. Claim next events using SKIP LOCKED
        events = await self.repository.claim_next_events(
            worker_id=self.worker_id,
            limit=self.max_concurrent_events,
            lock_lease_ms=self.lock_lease_ms,
        )

        if events:
            logger.debug(f"Outbox sweeper {self.worker_id} claimed {len(events)} events.")

            # 3. Execute concurrently
            tasks = [self.process_event(event) for event in events]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def process_event(self, event: ControlPlaneOutbox) -> None:
        try:
            await self.publisher.publish(event)
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug(f"Successfully processed outbox event {event.id} ({event.event_type})")
        except Exception as e:
            logger.error(
                f"Failed to process outbox event {event.id} ({event.event_type}): {e}",
                exc_info=True,
            )
            await self.repository.mark_failed(event.id, self.worker_id, str(e))
