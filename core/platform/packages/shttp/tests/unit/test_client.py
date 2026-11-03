"""Unit tests for HttpClient and factory."""

from __future__ import annotations

import httpx
import pytest
from shttp.client import HttpClient, create_http_client
from shttp.exceptions import HttpTimeoutError
from shttp.resilience import HttpBackoffHandler


def test_create_http_client() -> None:
    client = create_http_client()
    assert isinstance(client, httpx.AsyncClient)
    assert client.is_closed is False


def test_http_client_rejects_follow_redirects() -> None:
    unsafe_client = httpx.AsyncClient(follow_redirects=True)
    with pytest.raises(ValueError, match="follow_redirects=False"):
        HttpClient(client=unsafe_client)


@pytest.mark.asyncio
async def test_http_client_context_manager() -> None:
    async with HttpClient(allow_private_ips=True) as client:
        assert isinstance(client.raw_client, httpx.AsyncClient)
        assert client.raw_client.is_closed is False
    assert client.raw_client.is_closed is True


@pytest.mark.asyncio
async def test_http_client_uses_client_default_timeout() -> None:
    captured_timeout: dict[str, float | None] | None = None

    def capture_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_timeout
        captured_timeout = request.extensions.get("timeout")
        return httpx.Response(200)

    test_client = httpx.AsyncClient(transport=httpx.MockTransport(capture_handler), timeout=12.34)
    client = HttpClient(client=test_client, allow_private_ips=True)
    await client.get("http://127.0.0.1")
    assert captured_timeout is not None
    assert captured_timeout.get("connect") == 12.34
    await test_client.aclose()


@pytest.mark.asyncio
async def test_http_client_maps_timeout_error() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out", request=request)

    test_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    client = HttpClient(
        client=test_client,
        backoff_handler=HttpBackoffHandler(max_retries=0),
        allow_private_ips=True,
    )
    with pytest.raises(HttpTimeoutError):
        await client.get("http://127.0.0.1")
    await test_client.aclose()


@pytest.mark.asyncio
async def test_http_client_normalizes_authorization_headers_case_insensitively() -> None:
    captured_raw_headers: list[tuple[bytes, bytes]] = []

    class _StaticBearerProvider:
        async def get_access_token(self, client: HttpClient) -> str:
            del client
            return "fresh_bearer_token"

    def inspect_headers_handler(request: httpx.Request) -> httpx.Response:
        captured_raw_headers.clear()
        captured_raw_headers.extend(request.headers.raw)
        return httpx.Response(200)

    test_client = httpx.AsyncClient(transport=httpx.MockTransport(inspect_headers_handler))
    client = HttpClient(
        client=test_client,
        default_headers={"authorization": "Basic stale_default", "X-Tenant": "t1"},
        token_provider=_StaticBearerProvider(),
        allow_private_ips=True,
    )

    await client.get("http://127.0.0.1", headers={"X-Trace": "trc_1"})
    auth_headers = [
        val.decode() for key, val in captured_raw_headers if key.lower() == b"authorization"
    ]
    assert auth_headers == ["Bearer fresh_bearer_token"]
    assert (b"x-tenant", b"t1") in [(k.lower(), v) for k, v in captured_raw_headers]
    assert (b"x-trace", b"trc_1") in [(k.lower(), v) for k, v in captured_raw_headers]

    # Per-request lowercase authorization header must also replace without duplicating
    await client.get("http://127.0.0.1", headers={"authorization": "Bearer explicit_override"})
    override_auth_headers = [
        val.decode() for key, val in captured_raw_headers if key.lower() == b"authorization"
    ]
    assert override_auth_headers == ["Bearer explicit_override"]

    await test_client.aclose()
