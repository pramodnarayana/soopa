from typing import Protocol


class HttpDeliveryPort(Protocol):
    """
    Interface for performing outbound HTTP requests (Webhooks).
    """

    async def deliver(
        self,
        url: str,
        payload: bytes,
        auth_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, str]:
        """Sends the payload to the specified URL and returns the HTTP status code and response body."""
        ...
