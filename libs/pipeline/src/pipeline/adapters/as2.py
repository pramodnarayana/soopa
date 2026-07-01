"""
HTTPX-based adapter for outbound AS2 delivery.
Implements AS2DeliveryPort using an async HTTP client.
"""

import logging

import httpx
from pipeline.ports.as2 import AS2DeliveryPort

logger = logging.getLogger(__name__)


class HttpxAS2DeliveryAdapter(AS2DeliveryPort):
    """
    Concrete implementation of AS2DeliveryPort using HTTPX.

    Sends a raw AS2 HTTP POST to the trading partner's endpoint.
    Handles transport-level concerns only: timeouts, redirects, and
    connection errors. MDN parsing is delegated to the caller (DeliveryService).
    """

    def __init__(self, timeout_secs: int = 30) -> None:
        self.timeout = timeout_secs

    async def deliver(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        """
        Executes the AS2 HTTP POST.

        Raises:
            httpx.ConnectError: If the remote endpoint is unreachable.
            httpx.TimeoutException: If the connection or read times out.
        """
        logger.debug(f"AS2 HTTP POST → {url}, Content-Length={len(body)}")

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,  # AS2 spec does not permit redirect following
        ) as client:
            response = await client.post(url, content=body, headers=headers)

        logger.info(
            f"AS2 response from {url}: HTTP {response.status_code}, "
            f"Content-Length={len(response.content)}"
        )
        return response.status_code, response.content
