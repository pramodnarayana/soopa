import asyncio

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


class OutboxProcessorUseCase:
    """
    Application Service responsible for claiming outbox events and publishing them.
    Agnostic to how it is triggered (e.g. Postgres LISTEN/NOTIFY, polling, etc).
    """

    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        max_concurrent_events: int = 50,
        worker_id: str | None = None,
        lock_lease_ms: int = 30000,
    ):
        self.repository = repository
        self.publisher = publisher
        self.worker_id = worker_id or generate_id(SystemIdPrefix.GENERIC)
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False
        logger.info("outbox_processor_stopped", worker_id=self.worker_id)

    async def process_pending(self) -> bool:
        """
        Polls and processes messages.
        Returns True if more messages might be available (i.e. we hit max batch size), False otherwise.
        """
        if not self.is_running:
            return False

        events = await self.repository.claim_next_events(
            worker_id=self.worker_id,
            limit=self.max_concurrent_events,
            lock_lease_ms=self.lock_lease_ms,
        )

        if not events:
            return False

        logger.debug("outbox_relay_events_claimed", worker_id=self.worker_id, count=len(events))

        batch_failure_reason: str | None = None
        try:
            successful_ids = await self.publisher.publish_batch(events)
        except Exception as e:
            logger.exception("outbox_event_batch_publish_failed", error=str(e))
            successful_ids = []
            batch_failure_reason = str(e) or type(e).__name__

        if not successful_ids and batch_failure_reason is None:
            batch_failure_reason = "Batch publisher returned no successful event IDs"

        tasks = []
        for event in events:
            if event.id in successful_ids:
                logger.debug(
                    "outbox_event_published", event_id=event.id, event_type=event.event_type
                )
                tasks.append(self.repository.mark_completed(event.id, self.worker_id))
            else:
                logger.error("outbox_event_processing_failed", event_id=event.id)
                tasks.append(
                    self.repository.mark_failed(
                        event.id,
                        self.worker_id,
                        batch_failure_reason or "Event was not acknowledged by batch publisher",
                    )
                )

        await asyncio.gather(*tasks, return_exceptions=True)

        return len(events) >= self.max_concurrent_events
