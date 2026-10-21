"""
HTTPX-based adapter for outbound AS2 delivery.
Implements AS2DeliveryPort using an async HTTP client.
"""

from collections.abc import Callable

import httpx
import structlog
from shttp import (
    HttpBackoffHandler,
    HttpClient,
    HttpError,
    HttpNetworkError,
    HttpTimeoutError,
    SsrfSecurityError,
    create_http_client,
)

from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort
from edi.ports.outbound.exceptions import PortConnectionError, PortTimeoutError

logger = structlog.get_logger(__name__)


class HttpxAS2DeliveryClient(AS2DeliveryPort):
    """
    Concrete implementation of AS2DeliveryPort using HttpClient.

    Sends a raw AS2 HTTP POST to the trading partner's endpoint.
    Handles transport-level concerns only: timeouts, redirects, and
    connection errors. MDN parsing is delegated to the caller (DeliveryService).
    """

    def __init__(
        self,
        timeout_secs: int = 30,
        validator: Callable[[str], bool] | None = None,
        allow_private_ips: bool = False,
        client: HttpClient | None = None,
    ) -> None:
        self.timeout = timeout_secs
        self.validator = validator
        self.allow_private_ips = allow_private_ips
        self._owned_client = client is None
        if client is None:
            self._raw_client: httpx.AsyncClient | None = create_http_client(
                timeout=httpx.Timeout(float(timeout_secs), connect=10.0),
                follow_redirects=False,  # AS2 spec does not permit redirect following
            )
            self._client = HttpClient(
                self._raw_client,
                allow_private_ips=allow_private_ips,
                backoff_handler=HttpBackoffHandler(max_retries=0),
            )
        else:
            self._raw_client = None
            self._client = client

    async def deliver(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        """
        Executes the AS2 HTTP POST.

        Raises:
            PortConnectionError: If the remote endpoint is unreachable.
            PortTimeoutError: If the connection or read times out.
            ValueError: If URL validation fails.
        """
        logger.debug(
            "as2_http_post_initiating",
            url=url,
            content_length=len(body),
        )

        if self.validator and not self.validator(url):
            raise ValueError("URL validation failed for provided destination.")

        try:
            response = await self._client.post(
                url,
                content=body,
                headers=headers,
                timeout=float(self.timeout),
                allow_private_ips=self.allow_private_ips,
            )
        except SsrfSecurityError:
            raise
        except HttpTimeoutError as e:
            raise PortTimeoutError(f"AS2 connection timed out: {e}") from e
        except (HttpNetworkError, HttpError, httpx.RequestError) as e:
            raise PortConnectionError(f"AS2 connection failed: {e}") from e

        # Convert headers to a standard dict
        resp_headers = {k.lower(): v for k, v in response.headers.items()}

        logger.info(
            "as2_http_post_response",
            url=url,
            status_code=response.status_code,
            content_length=len(response.content),
        )
        return response.status_code, resp_headers, response.content

    async def close(self) -> None:
        if self._owned_client and self._raw_client:
            await self._raw_client.aclose()
