"""Concrete implementation of HttpDeliveryPort using centralized webhooks platform package."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from shttp import (
    HttpBackoffHandler,
    HttpClient,
    SsrfSecurityError,
    SsrfViolationReason,
    create_http_client,
)
from webhooks.dispatchers import ResilientWebhookDispatcher
from webhooks.dispatchers.domain.delivery import (
    WebhookDeliveryFailureType,
    WebhookDispatchCommand,
)
from webhooks.dispatchers.ports.webhook_dispatcher_port import WebhookDispatcherPort

from edi.ports.outbound.exceptions import PortConnectionError, PortTimeoutError
from edi.ports.outbound.http_delivery_port import HttpDeliveryPort


class HttpxDeliveryClient(HttpDeliveryPort):
    """Concrete implementation of HttpDeliveryPort delegating to centralized ResilientWebhookDispatcher."""

    def __init__(
        self,
        timeout_secs: int = 30,
        validator: Callable[[str], bool] | None = None,
        allow_private_ips: bool = False,
        client: HttpClient | None = None,
        dispatcher: WebhookDispatcherPort | None = None,
    ) -> None:
        self.timeout = timeout_secs
        self.validator = validator
        self.allow_private_ips = allow_private_ips
        self._owned_client = client is None
        if client is None:
            self._raw_client: httpx.AsyncClient | None = create_http_client(
                timeout=httpx.Timeout(float(timeout_secs), connect=10.0),
                follow_redirects=False,
            )
            self._client = HttpClient(
                self._raw_client,
                allow_private_ips=allow_private_ips,
                backoff_handler=HttpBackoffHandler(max_retries=0),
            )
        else:
            self._raw_client = None
            self._client = client

        self._dispatcher = dispatcher or ResilientWebhookDispatcher(
            client=self._client,
            default_timeout_seconds=float(timeout_secs),
        )

    async def deliver(
        self,
        url: str,
        payload: bytes,
        auth_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, str]:
        if self.validator and not self.validator(url):
            raise ValueError("URL validation failed for provided destination.")

        cmd = WebhookDispatchCommand(
            tenant_id="",
            subscription_id="",
            url=url,
            payload=payload,
            auth_token=auth_token,
            idempotency_key=idempotency_key,
            timeout_seconds=float(self.timeout),
            allow_private_ips=self.allow_private_ips,
        )

        result = await self._dispatcher.dispatch(cmd)

        if not result.is_success:
            if result.failure_type == WebhookDeliveryFailureType.TIMEOUT:
                raise PortTimeoutError(f"HTTP connection timed out: {result.error_message}")
            if result.failure_type == WebhookDeliveryFailureType.SSRF:
                raise SsrfSecurityError(
                    result.error_message or "SSRF Security Violation",
                    url=url,
                    reason=SsrfViolationReason.RESTRICTED_IP,
                )
            if result.failure_type == WebhookDeliveryFailureType.NETWORK_ERROR:
                raise PortConnectionError(f"HTTP connection failed: {result.error_message}")

        return result.status_code, result.response_body

    async def close(self) -> None:
        if self._owned_client and self._raw_client:
            await self._raw_client.aclose()
        if isinstance(self._dispatcher, ResilientWebhookDispatcher):
            await self._dispatcher.close()
