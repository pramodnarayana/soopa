from typing import Protocol


class HttpDeliveryPort(Protocol):
    """
    Interface for performing outbound HTTP requests (Webhooks).
    """

    async def deliver(self, url: str, payload: bytes) -> int:
        """Sends the payload to the specified URL and returns the HTTP status code."""
        ...
