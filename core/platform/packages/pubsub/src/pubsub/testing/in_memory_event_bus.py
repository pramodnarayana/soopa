import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pubsub.aws.aws_sqs_consumer import AckableMessage


class InMemoryEventBus:
    """
    A pure in-memory event bus for testing.
    Can be used as a drop-in replacement for AwsSnsPublisher and AwsSqsConsumer
    to test the Outbox -> Dispatcher flow without spinning up Localstack SQS/SNS.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def publish(self, topic_arn_or_queue: str, payload: dict[str, Any]) -> None:
        """Simulate publishing a message to SNS or directly to SQS."""
        # For simplicity, we just dump the payload into the in-memory queue.
        # This skips the SNS envelope wrapping since we're testing the domain flow, not AWS.
        await self.queue.put(payload)

    async def publish_batch(self, events: list[dict[str, Any]]) -> list[str]:
        """Simulate publishing a batch of messages."""
        import dataclasses

        successful_ids = []
        for event in events:
            payload = dataclasses.asdict(event) if dataclasses.is_dataclass(event) else event
            await self.queue.put(payload)
            # Assuming the event dict has an 'id' field, like OutboxEvent
            successful_ids.append(payload.get("id", "unknown_id"))
        return successful_ids

    @asynccontextmanager
    async def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]:
        if self.queue.empty():
            yield None
            return

        payload = await self.queue.get()

        async def ack() -> None:
            self.queue.task_done()

        async def nack() -> None:
            # Re-enqueue the message
            await self.queue.put(payload)
            self.queue.task_done()

        yield AckableMessage(payload=payload, ack=ack, nack=nack)

    async def clear(self) -> None:
        """Clear the queue."""
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
