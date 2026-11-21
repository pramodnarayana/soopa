"""In-Memory Outbox Publisher implementing OutboxPublisherPort for testing."""

from __future__ import annotations

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class InMemoryOutboxPublisher(OutboxPublisherPort):
    """
    In-memory outbox publisher for zero-infrastructure testing.
    Records published events in an in-memory list for assertion.
    """

    def __init__(self, destination_uri: str = "memory://outbox") -> None:
        self.destination_uri = destination_uri
        self.published_events: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published_events.append(event)
        logger.info(
            "in_memory_outbox_event_published",
            destination=self.destination_uri,
            event_id=event.id,
        )

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        successful_ids: list[str] = []
        for event in events:
            self.published_events.append(event)
            successful_ids.append(event.id)
        return successful_ids
