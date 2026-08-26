from typing import Protocol

from platform_orm.events import EventEnvelope


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
        Publishes a batch of event envelopes.
        Returns a list of successfully published event IDs.
        """
        ...
