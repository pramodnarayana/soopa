import asyncio

import structlog
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork import SystemIdPrefix, generate_id

logger = structlog.get_logger(__name__)


class OutboxSweeperUseCase:
    """
    Application UseCase to sweep the Outbox.
    It continuously picks up batches of stuck or pending events and publishes them
    until the outbox is drained.
    """

    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        max_concurrent_events: int = 50,
        lock_lease_ms: int = 30000,
    ):
        self.repository = repository
        self.publisher = publisher
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.worker_id = generate_id(SystemIdPrefix.GENERIC)

    async def execute(self) -> None:
        logger.info("sweep_outbox_started", worker_id=self.worker_id)
        total_processed = 0

        # 1. Sweep stuck events (Repository handles chunking internally)
        swept = await self.repository.sweep_stuck_events(self.lock_lease_ms)
        if swept > 0:
            logger.info("stuck_events_swept", count=swept, target_status=OutboxStatus.PENDING.value)

        # 2. Drain pending events using chunked iteration
        while True:
            events = await self.repository.claim_next_events(
                worker_id=self.worker_id,
                limit=self.max_concurrent_events,
                lock_lease_ms=self.lock_lease_ms,
            )

            if not events:
                break  # Drained completely

            logger.debug("sweeper_events_claimed", worker_id=self.worker_id, count=len(events))

            # 3. Execute batch publish
            try:
                successful_ids = await self.publisher.publish_batch(events)
            except Exception:
                logger.exception("outbox_event_batch_publish_failed_by_sweeper")
                successful_ids = []

            tasks = []
            for event in events:
                if event.id in successful_ids:
                    logger.debug(
                        "outbox_event_processed_by_sweeper",
                        event_id=event.id,
                        event_type=event.event_type,
                    )
                    tasks.append(self._safe_mark_completed(event.id))
                    total_processed += 1
                else:
                    logger.error(
                        "outbox_event_publishing_failed_by_sweeper",
                        event_id=event.id,
                        event_type=event.event_type,
                    )
                    tasks.append(self._safe_mark_failed(event.id, "Failed to publish in batch"))

            await asyncio.gather(*tasks, return_exceptions=True)

            # 4. Yield execution to allow DB and Event Loop to breathe
            await asyncio.sleep(0.1)

        logger.info("sweep_outbox_completed", events_processed=total_processed)

    async def _safe_mark_completed(self, event_id: str) -> None:
        try:
            await self.repository.mark_completed(event_id, self.worker_id)
        except Exception:
            logger.exception("outbox_event_mark_completed_error", event_id=event_id)

    async def _safe_mark_failed(self, event_id: str, error_msg: str) -> None:
        try:
            await self.repository.mark_failed(event_id, self.worker_id, error_msg)
        except Exception:
            logger.exception("outbox_event_mark_failed_error", event_id=event_id)
