"""Unit tests for ResilientWebhookDispatcher."""

from __future__ import annotations

import httpx
import pytest
from shttp import HttpClient
from webhooks.crypto.hmac_verifier import timing_safe_verify_hmac
from webhooks.dispatchers.adapters.http.resilient_dispatcher import ResilientWebhookDispatcher
from webhooks.dispatchers.domain.models import WebhookDispatchCommand


@pytest.mark.asyncio
async def test_resilient_dispatcher_successful_post() -> None:
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"received": True})

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    http_client = HttpClient(raw_client, allow_private_ips=True)
    dispatcher = ResilientWebhookDispatcher(client=http_client)

    cmd = WebhookDispatchCommand(
        tenant_id="tenant_1",
        subscription_id="sub_123",
        url="http://127.0.0.1:8080/webhook",
        payload={"event": "invoice.paid", "amount": 100},
        event_type="invoice.paid",
        secret="whsec_partner_secret",
        idempotency_key="idemp_abc",
        auth_token="Bearer my_partner_token",
        allow_private_ips=True,
    )

    result = await dispatcher.dispatch(cmd)

    assert result.is_success is True
    assert result.status_code == 200
    assert result.error_message is None
    assert len(captured_requests) == 1

    req = captured_requests[0]
    assert req.headers["X-Event-Type"] == "invoice.paid"
    assert req.headers["Idempotency-Key"] == "idemp_abc"
    assert req.headers["Authorization"] == "Bearer my_partner_token"

    sig_header = req.headers["X-Signature-256"]
    assert sig_header.startswith("sha256=")
    sig = sig_header[7:]
    assert timing_safe_verify_hmac("whsec_partner_secret", req.content, sig) is True


@pytest.mark.asyncio
async def test_resilient_dispatcher_handles_http_error() -> None:
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    raw_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    http_client = HttpClient(raw_client, allow_private_ips=True)
    dispatcher = ResilientWebhookDispatcher(client=http_client)

    cmd = WebhookDispatchCommand(
        tenant_id="tenant_1",
        subscription_id="sub_123",
        url="http://127.0.0.1:8080/webhook",
        payload=b"test",
        allow_private_ips=True,
    )

    result = await dispatcher.dispatch(cmd)
    assert result.is_success is False
    assert result.status_code == 500
    assert "HTTP 500" in (result.error_message or "")


@pytest.mark.asyncio
async def test_resilient_dispatcher_handles_ssrf_block() -> None:
    # When allow_private_ips is False (default), private IPs are blocked with SSRF error
    dispatcher = ResilientWebhookDispatcher()
    cmd = WebhookDispatchCommand(
        tenant_id="tenant_1",
        subscription_id="sub_123",
        url="http://192.168.1.1/internal",
        payload=b"test",
        allow_private_ips=False,
    )

    result = await dispatcher.dispatch(cmd)
    assert result.is_success is False
    assert result.status_code == 403
    assert "SSRF" in (result.error_message or "")
    await dispatcher.close()
