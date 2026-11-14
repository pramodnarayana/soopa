"""Resilient outbound webhook dispatcher using centralized shttp client."""

from __future__ import annotations

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

from webhooks.crypto.hmac_signer import sign_payload
from webhooks.dispatchers.domain.models import WebhookDeliveryResult, WebhookDispatchCommand
from webhooks.dispatchers.ports.webhook_dispatcher_port import WebhookDispatcherPort

logger = structlog.get_logger(__name__)


class ResilientWebhookDispatcher(WebhookDispatcherPort):
    """Production implementation of WebhookDispatcherPort using shttp with SSRF protection,

    automatic HMAC-SHA256 signing, and structured outcome reporting.
    """

    def __init__(
        self,
        client: HttpClient | None = None,
        default_timeout_seconds: float = 30.0,
    ) -> None:
        self._default_timeout = default_timeout_seconds
        self._owned_client = client is None
        if client is None:
            self._raw_client: httpx.AsyncClient | None = create_http_client(
                timeout=httpx.Timeout(self._default_timeout, connect=10.0),
                follow_redirects=False,
            )
            self._client = HttpClient(
                self._raw_client,
                allow_private_ips=False,
                backoff_handler=HttpBackoffHandler(max_retries=0),
            )
        else:
            self._raw_client = None
            self._client = client

    async def dispatch(self, command: WebhookDispatchCommand) -> WebhookDeliveryResult:
        log = logger.bind(
            tenant_id=command.tenant_id,
            subscription_id=command.subscription_id,
            url=command.url,
            event_type=command.event_type,
        )

        raw_payload = command.payload_bytes
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **command.headers,
        }

        if command.event_type:
            headers["X-Event-Type"] = command.event_type

        if command.idempotency_key:
            headers["Idempotency-Key"] = command.idempotency_key

        if command.auth_token:
            headers["Authorization"] = command.auth_token

        if command.secret:
            signature = sign_payload(command.secret, raw_payload)
            headers["X-Signature-256"] = f"sha256={signature}"

        timeout = command.timeout_seconds or self._default_timeout

        try:
            response = await self._client.post(
                command.url,
                content=raw_payload,
                headers=headers,
                timeout=timeout,
                allow_private_ips=command.allow_private_ips,
            )
            status_code = response.status_code
            text = response.text
            is_success = 200 <= status_code < 300

            if is_success:
                log.info("webhook_dispatch.succeeded", status_code=status_code)
            else:
                log.error("webhook_dispatch.http_error", status_code=status_code)

            return WebhookDeliveryResult(
                status_code=status_code,
                response_body=text,
                is_success=is_success,
                error_message=None if is_success else f"HTTP {status_code}: {text}",
            )
        except SsrfSecurityError as e:
            log.error("webhook_dispatch.ssrf_blocked", error=str(e))
            return WebhookDeliveryResult(
                status_code=403,
                response_body="",
                is_success=False,
                error_message=f"SSRF Security Violation: {e}",
            )
        except HttpTimeoutError as e:
            log.error("webhook_dispatch.timed_out", error=str(e))
            return WebhookDeliveryResult(
                status_code=504,
                response_body="",
                is_success=False,
                error_message=f"Connection Timeout: {e}",
            )
        except (HttpNetworkError, HttpError, httpx.RequestError) as e:
            log.error("webhook_dispatch.network_error", error=str(e))
            return WebhookDeliveryResult(
                status_code=502,
                response_body="",
                is_success=False,
                error_message=f"Network Error: {e}",
            )

    async def close(self) -> None:
        if self._owned_client and self._raw_client:
            await self._raw_client.aclose()
