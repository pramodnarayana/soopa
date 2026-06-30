from collections.abc import Callable

import httpx
from pipeline.ports.http import HttpDeliveryPort


class HttpxDeliveryAdapter(HttpDeliveryPort):
    """
    Concrete implementation of HttpDeliveryPort using HTTPX.
    """

    def __init__(self, timeout_secs: int = 30, validator: Callable[[str], bool] | None = None):
        self.timeout = timeout_secs
        self.validator = validator

    async def deliver(self, url: str, payload: bytes, auth_token: str | None = None) -> int:
        if self.validator and not self.validator(url):
            raise ValueError("URL validation failed for provided destination.")

        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = auth_token

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.post(url, content=payload, headers=headers)
            return response.status_code
