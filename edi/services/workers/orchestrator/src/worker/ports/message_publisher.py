import abc
from contextlib import AbstractAsyncContextManager
from typing import Any


class MessagePublisherPort(abc.ABC):
    @abc.abstractmethod
    def connect(self) -> AbstractAsyncContextManager["MessagePublisherPort"]:
        """
        Context manager to establish and share the underlying connection pool.
        Must be entered before calling publish_batch.
        """
        pass

    @abc.abstractmethod
    async def publish_batch(self, queue_name: str, messages: list[dict[str, Any]]) -> list[str]:
        """
        Publishes a batch of messages to the specified queue.
        Each message dict MUST contain an "Id" key (string) used for batch deduplication.
        Returns a list of the "Id"s that were successfully published.
        """
        pass
