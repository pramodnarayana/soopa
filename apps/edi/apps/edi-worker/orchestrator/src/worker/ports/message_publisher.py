import abc
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublishMessageEnvelope:
    message_id: str
    event_type: str
    event: dict[str, Any]
    idempotency_key: str | None = None
    partition_key: str | None = None


class MessagePublisherPort(abc.ABC):
    @abc.abstractmethod
    def connect(self) -> AbstractAsyncContextManager["MessagePublisherPort"]:
        """
        Context manager to establish and share the underlying connection pool.
        Must be entered before calling publish_batch.
        """
        pass

    @abc.abstractmethod
    async def publish_batch(
        self, queue_name: str, messages: list[PublishMessageEnvelope]
    ) -> list[str]:
        """
        Publishes a batch of messages to the specified queue.
        Returns a list of the message_ids that were successfully published.
        """
        pass
