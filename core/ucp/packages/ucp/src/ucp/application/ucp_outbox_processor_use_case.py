import asyncio
import uuid

import structlog

from ucp.domain.models.outbox_event import OutboxEvent
from ucp.ports.outbox_publisher import OutboxPublisherPort
from ucp.ports.outbox_repository import OutboxRepositoryPort

logger = structlog.get_logger(__name__)


class UcpOutboxProcessorUseCase:
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
        self.worker_id = worker_id or str(uuid.uuid4())
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False
        logger.info("ucp_outbox_processor_stopped", worker_id=self.worker_id)

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

        logger.debug("ucp_relay_events_claimed", worker_id=self.worker_id, count=len(events))

        tasks = [self.process_event(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)

        return len(events) >= self.max_concurrent_events

    async def process_event(self, event: OutboxEvent) -> None:
        try:
            await self.publisher.publish(event)
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug(
                "ucp_outbox_event_published", event_id=event.id, event_type=event.event_type
            )
        except Exception as e:
            logger.exception("ucp_outbox_event_processing_failed", event_id=event.id)
            await self.repository.mark_failed(event.id, self.worker_id, str(e))
