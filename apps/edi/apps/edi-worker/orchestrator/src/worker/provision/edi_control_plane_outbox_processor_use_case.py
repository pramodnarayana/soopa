import asyncio
import uuid

import structlog

from worker.ports.outbox_relay_publisher import OutboxRelayPublisherPort
from worker.ports.outbox_relay_repository import OutboxRelayRepositoryPort, RelayOutboxEvent

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxProcessorUseCase:
    """
    Application Service responsible for claiming outbox events and publishing them.
    Agnostic to how it is triggered (e.g. Postgres LISTEN/NOTIFY, polling, etc).
    """

    def __init__(
        self,
        repository: OutboxRelayRepositoryPort,
        publisher: OutboxRelayPublisherPort,
        max_concurrent_events: int = 50,
        worker_id: str | None = None,
    ):
        self.repository = repository
        self.publisher = publisher
        self.worker_id = worker_id or str(uuid.uuid4())
        self.max_concurrent_events = max_concurrent_events
        self.is_running = True

    def stop(self) -> None:
        self.is_running = False
        logger.info("edi_outbox_processor_stopped", worker_id=self.worker_id)

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
        )

        if not events:
            return False

        logger.debug("edi_relay_events_claimed", worker_id=self.worker_id, count=len(events))

        tasks = [self.process_event(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)

        return len(events) >= self.max_concurrent_events

    async def process_event(self, event: RelayOutboxEvent) -> None:
        try:
            await self.publisher.publish(event)
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug(
                "edi_outbox_event_published", event_id=event.id, event_type=event.event_type
            )
        except Exception as e:
            logger.exception("edi_outbox_event_processing_failed", event_id=event.id)
            await self.repository.mark_failed(event.id, self.worker_id, str(e))
