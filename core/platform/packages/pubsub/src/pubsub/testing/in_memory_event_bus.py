import asyncio
import copy
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType

from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.message import AckableMessage
from pubsub.ports.message_consumer_port import MessageConsumerPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope


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
        self.queue: asyncio.Queue[JsonDict] = asyncio.Queue()

    # -------------------------------------------------------------------------
    # MessageConsumerPort — async context manager for connection lifecycle
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "InMemoryEventBus":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass  # No real connection to release

    # -------------------------------------------------------------------------
    # OutboxPublisherPort — producer side
    # -------------------------------------------------------------------------

    @staticmethod
    def _envelope_to_dict(event: EventEnvelope) -> JsonDict:
        return copy.deepcopy(event.to_dict())

    async def publish(self, event: EventEnvelope) -> None:
        """Enqueue a single EventEnvelope as its dict representation."""
        await self.queue.put(self._envelope_to_dict(event))

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        """
        Enqueue all events and return their IDs as successfully published.
        Satisfies OutboxPublisherPort exactly — accepts list[EventEnvelope], not list[Any].
        """
        successful_ids: list[str] = []
        for event in events:
            await self.queue.put(self._envelope_to_dict(event))
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

        stored_payload = await self.queue.get()
        acknowledged = False

        async def ack() -> None:
            nonlocal acknowledged
            self.queue.task_done()
            acknowledged = True

        async def nack(*, visibility_timeout_seconds: int | None = None) -> None:
            nonlocal acknowledged
            if visibility_timeout_seconds is not None and visibility_timeout_seconds > 0:
                await asyncio.sleep(visibility_timeout_seconds)
            # Re-enqueue an isolated broker copy to simulate SQS redelivery after visibility timeout
            await self.queue.put(copy.deepcopy(stored_payload))
            self.queue.task_done()
            acknowledged = True

        try:
            yield AckableMessage(payload=copy.deepcopy(stored_payload), ack=ack, nack=nack)
        finally:
            if not acknowledged:
                await self.queue.put(copy.deepcopy(stored_payload))
                self.queue.task_done()

    # -------------------------------------------------------------------------
    # Test helpers
    # -------------------------------------------------------------------------

    async def clear(self) -> None:
        """Drain the queue. Useful for test teardown."""
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
