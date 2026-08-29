import asyncio
import dataclasses
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from database.events import EventEnvelope
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.aws.aws_sqs_consumer import AckableMessage
from pubsub.ports.message_consumer_port import MessageConsumerPort


class InMemoryEventBus(OutboxPublisherPort, MessageConsumerPort):
    """
    Pure in-memory event bus for integration testing.

    Implements both OutboxPublisherPort (producer side) and MessageConsumerPort
    (consumer side), making it a self-contained drop-in replacement for the full
    SNS + SQS pipeline without requiring Localstack.

    Type safety: both port signatures are satisfied exactly, so mypy validates
    test harnesses that accept these ports.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # -------------------------------------------------------------------------
    # MessageConsumerPort — async context manager for connection lifecycle
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "InMemoryEventBus":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass  # No real connection to release

    # -------------------------------------------------------------------------
    # OutboxPublisherPort — producer side
    # -------------------------------------------------------------------------

    async def publish(self, event: EventEnvelope) -> None:
        """Enqueue a single EventEnvelope as its dict representation."""
        await self.queue.put(dataclasses.asdict(event))

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        """
        Enqueue all events and return their IDs as successfully published.
        Satisfies OutboxPublisherPort exactly — accepts list[EventEnvelope], not list[Any].
        """
        successful_ids: list[str] = []
        for event in events:
            await self.queue.put(dataclasses.asdict(event))
            successful_ids.append(event.id)
        return successful_ids

    # -------------------------------------------------------------------------
    # MessageConsumerPort — consumer side
    # -------------------------------------------------------------------------

    @asynccontextmanager
    async def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]:
        if self.queue.empty():
            yield None
            return

        payload = await self.queue.get()

        async def ack() -> None:
            self.queue.task_done()

        async def nack() -> None:
            # Re-enqueue the message to simulate SQS redelivery after visibility timeout
            await self.queue.put(payload)
            self.queue.task_done()

        yield AckableMessage(payload=payload, ack=ack, nack=nack)

    # -------------------------------------------------------------------------
    # Test helpers
    # -------------------------------------------------------------------------

    async def clear(self) -> None:
        """Drain the queue. Useful for test teardown."""
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
