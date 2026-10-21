from collections.abc import Callable

import httpx
from shttp import (
    HttpClient,
    HttpError,
    HttpNetworkError,
    HttpTimeoutError,
    SsrfSecurityError,
    create_http_client,
)

from edi.ports.outbound.exceptions import PortConnectionError, PortTimeoutError
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort


class HttpxDeliveryClient(HttpDeliveryPort):
    """
    Concrete implementation of HttpDeliveryPort using HttpClient.
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
        self._client = client or HttpClient(
            create_http_client(
                timeout=httpx.Timeout(float(timeout_secs), connect=10.0),
                follow_redirects=False,
            ),
            allow_private_ips=allow_private_ips,
        )

    async def deliver(
        self,
        url: str,
        payload: bytes,
        auth_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, str]:
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = auth_token
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        if self.validator and not self.validator(url):
            raise ValueError("URL validation failed for provided destination.")

        try:
            response = await self._client.post(
                url,
                content=payload,
                headers=headers,
                timeout=float(self.timeout),
                allow_private_ips=self.allow_private_ips,
            )
            return response.status_code, response.text
        except SsrfSecurityError:
            raise
        except HttpTimeoutError as e:
            raise PortTimeoutError(f"HTTP connection timed out: {e}") from e
        except (HttpNetworkError, HttpError, httpx.RequestError) as e:
            raise PortConnectionError(f"HTTP connection failed: {e}") from e

    async def close(self) -> None:
        await self._client.close()
