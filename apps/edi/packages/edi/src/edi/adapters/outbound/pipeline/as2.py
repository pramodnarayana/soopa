"""
HTTPX-based adapter for outbound AS2 delivery.
Implements AS2DeliveryPort using an async HTTP client.
"""

import typing

import httpx
import structlog

from edi.adapters.outbound.security.network import ssrf_safe_context
from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort

logger = structlog.get_logger(__name__)


class HttpxAS2DeliveryClient(AS2DeliveryPort):
    """
    Concrete implementation of AS2DeliveryPort using HTTPX.

    Sends a raw AS2 HTTP POST to the trading partner's endpoint.
    Handles transport-level concerns only: timeouts, redirects, and
    connection errors. MDN parsing is delegated to the caller (DeliveryService).
    """

    def __init__(
        self, timeout_secs: int = 30, validator: typing.Callable[[str], typing.Any] | None = None
    ) -> None:
        self.timeout = timeout_secs
        self.validator = validator

    async def deliver(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        """
        Executes the AS2 HTTP POST.

        Raises:
            httpx.ConnectError: If the remote endpoint is unreachable.
            httpx.TimeoutException: If the connection or read times out.
        """
        logger.debug("AS2 HTTP POST → {url}, Content-Length={len(body)}", url=url, val_1=len(body))

        import contextlib

        ctx = self.validator(url) if self.validator else contextlib.nullcontext()

        # If validator returns a boolean (legacy), handle it
        if isinstance(ctx, bool):
            if not ctx:
                raise ValueError("URL validation failed for provided destination.")
            ctx = contextlib.nullcontext()

        with ctx, ssrf_safe_context(url):
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,  # AS2 spec does not permit redirect following
            ) as client:
                response = await client.post(url, content=body, headers=headers)

        # Convert httpx headers to a standard dict
        resp_headers = {k.lower(): v for k, v in response.headers.items()}

        logger.info(
            "AS2 response from {url}: HTTP {response.status_code}, "
            "Content-Length={len(response.content)}"
        )
        return response.status_code, resp_headers, response.content
