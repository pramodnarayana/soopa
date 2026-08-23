from collections.abc import Callable
from typing import Any

import httpx

from edi.ports.outbound.http_delivery_port import HttpDeliveryPort


class HttpxDeliveryClient(HttpDeliveryPort):
    """
    Concrete implementation of HttpDeliveryPort using HTTPX.
    """

    def __init__(self, timeout_secs: int = 30, validator: Callable[[str], Any] | None = None):
        self.timeout = timeout_secs
        self.validator = validator

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

        import contextlib

        ctx = self.validator(url) if self.validator else contextlib.nullcontext()

        # If validator returns a boolean (legacy), handle it
        if isinstance(ctx, bool):
            if not ctx:
                raise ValueError("URL validation failed for provided destination.")
            ctx = contextlib.nullcontext()

        with ctx:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.post(url, content=payload, headers=headers)
                return response.status_code, response.text
