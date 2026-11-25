from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from outbox.domain.models import BatchPublishOutcome
from seedwork.events import EventEnvelope


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


@runtime_checkable
class StructuredOutboxPublisherPort(OutboxPublisherPort, Protocol):
    """Extension of OutboxPublisherPort returning per-event ACK/NACK/DLQ dispositions."""

    async def publish_batch_structured(
        self, events: Sequence[EventEnvelope]
    ) -> list[BatchPublishOutcome]:
        """Publishes/dispatches a batch and returns explicit per-event dispositions."""
        ...
