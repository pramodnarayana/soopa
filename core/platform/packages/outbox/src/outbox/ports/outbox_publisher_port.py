from typing import Protocol

from database.events import EventEnvelope


class OutboxPublisherPort(Protocol):
    """
    Protocol for publishing outbox events to a message broker (e.g., SNS, Kafka).
    This is pure Python, completely abstracted from the underlying transport.
    """

    async def publish(self, event: EventEnvelope) -> None:
        """
        Publishes a single event envelope.
        Should raise an exception if publishing fails, so the caller can retry.
        """
        ...

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        """
        Publish a batch and return only the successfully acknowledged event IDs.

        Implementations must return partial successful IDs without raising when individual
        entries fail. A transport failure that prevents every entry from being attempted or
        acknowledged must be propagated so the processor can preserve its failure reason.
        """
        ...
