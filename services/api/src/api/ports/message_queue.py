from typing import Any, Protocol


class MessageQueuePort(Protocol):
    """
    Port (Interface) for sending messages to a queue.
    Business logic depends ONLY on this protocol, not on SQS or infrastructure.
    """

    async def send(self, queue_name: str, payload: dict[str, Any]) -> None:
        """Sends a dictionary payload to the specified queue."""
        ...
