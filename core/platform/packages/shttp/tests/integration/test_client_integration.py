"""Narrow integration tests connecting HttpClient to a live test HTTP server."""

from __future__ import annotations

import json
import time

import pytest
from pytest_httpserver import HTTPServer
from shttp.client import HttpClient
from shttp.exceptions import (
    FailureDisposition,
    HttpAuthError,
    HttpFailureClassification,
    HttpNetworkError,
    HttpTimeoutError,
    SsrfSecurityError,
    SsrfViolationReason,
    TimeoutKind,
)
from shttp.policy import RaiseForStatusPolicy, StandardJsonBodyErrorPredicate
from shttp.resilience import ExponentialBackoffStrategy, HttpBackoffHandler
from shttp.types import HttpRequest
from werkzeug.wrappers import Request, Response


@pytest.mark.asyncio
async def test_integration_real_http_methods(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/health", method="GET").respond_with_json({"status": "healthy"})
    httpserver.expect_request("/users", method="POST").respond_with_json(
        {"id": "usr_100"}, status=201
    )
    httpserver.expect_request("/users/usr_100", method="PUT").respond_with_json({"updated": True})
    httpserver.expect_request("/users/usr_100", method="DELETE").respond_with_data("", status=204)

    client = HttpClient(allow_private_ips=True)
    base_url = httpserver.url_for("")

    resp_get = await client.get(f"{base_url}/health")
    assert resp_get.status_code == 200
    assert resp_get.json() == {"status": "healthy"}

    resp_post = await client.post(f"{base_url}/users", json={"name": "Alice"})
    assert resp_post.status_code == 201
    assert resp_post.json() == {"id": "usr_100"}

    resp_put = await client.put(f"{base_url}/users/usr_100", json={"name": "Alice Updated"})
    assert resp_put.status_code == 200
    assert resp_put.json() == {"updated": True}

    resp_del = await client.delete(f"{base_url}/users/usr_100")
    assert resp_del.status_code == 204

    await client.close()


@pytest.mark.asyncio
async def test_integration_rate_limit_backoff_and_recovery(httpserver: HTTPServer) -> None:
    # First request: 429 with 1-second Retry-After; Second request: 200 OK
    call_count = 0

    def rate_limit_handler(request: Request) -> Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response("Too Many Requests", status=429, headers={"Retry-After": "1"})
        return Response(
            json.dumps({"data": "recovered"}), status=200, content_type="application/json"
        )

    httpserver.expect_request("/rate-limited", method="GET").respond_with_handler(
        rate_limit_handler
    )

    client = HttpClient(allow_private_ips=True)
    resp = await client.get(httpserver.url_for("/rate-limited"))

    assert resp.status_code == 200
    assert resp.json() == {"data": "recovered"}
    assert call_count == 2
    await client.close()


@pytest.mark.asyncio
async def test_integration_transient_503_recovery(httpserver: HTTPServer) -> None:
    call_count = 0

    def transient_handler(request: Request) -> Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response("Service Unavailable", status=503)
        return Response(
            json.dumps({"status": "online"}), status=200, content_type="application/json"
        )

    httpserver.expect_request("/flakey", method="GET").respond_with_handler(transient_handler)

    fast_backoff = HttpBackoffHandler(
        max_retries=2,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.05)],
    )
    client = HttpClient(backoff_handler=fast_backoff, allow_private_ips=True)
    resp = await client.get(httpserver.url_for("/flakey"))

    assert resp.status_code == 200
    assert resp.json() == {"status": "online"}
    assert call_count == 2
    await client.close()


@pytest.mark.asyncio
async def test_integration_ssrf_blocking_private_loopback(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/private-data").respond_with_json({"sensitive": "keys"})

    # By default, allow_private_ips=False
    client = HttpClient(allow_private_ips=False)

    with pytest.raises(SsrfSecurityError) as exc_info:
        await client.get(httpserver.url_for("/private-data"))

    assert exc_info.value.reason == SsrfViolationReason.RESTRICTED_IP
    assert exc_info.value.classify() == HttpFailureClassification.SECURITY_VIOLATION
    assert exc_info.value.disposition == FailureDisposition.FAIL
    await client.close()


@pytest.mark.asyncio
async def test_integration_pseudo_success_error_detection(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/api/graphql").respond_with_json(
        {"errors": [{"message": "Unauthorized access token"}]},
        status=200,
    )

    client = HttpClient(
        allow_private_ips=True,
        response_policy=RaiseForStatusPolicy(body_predicates=[StandardJsonBodyErrorPredicate()]),
    )

    with pytest.raises(HttpAuthError) as exc_info:
        await client.post(httpserver.url_for("/api/graphql"), json={"query": "{ me }"})

    assert exc_info.value.status_code == 401
    assert exc_info.value.disposition == FailureDisposition.FAIL
    assert exc_info.value.classify() == HttpFailureClassification.AUTH_FAILURE
    await client.close()


@pytest.mark.asyncio
async def test_integration_send_http_request_dto(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/orders",
        method="POST",
        query_string="filter=recent&limit=10",
        headers={"X-Correlation-Id": "dto-corr-456"},
    ).respond_with_json({"order_id": "ord_999"}, status=201)

    client = HttpClient(allow_private_ips=True)
    req = HttpRequest(
        method="POST",
        url=f"{httpserver.url_for('/api/orders')}",
        headers={"X-Correlation-Id": "dto-corr-456"},
        params={"filter": "recent", "limit": 10},
        json={"product": "widget", "quantity": 5},
    )

    resp = await client.send(req)
    assert resp.status_code == 201
    assert resp.json() == {"order_id": "ord_999"}
    await client.close()


@pytest.mark.asyncio
async def test_integration_form_data_urlencoded(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/oauth/token",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).respond_with_json({"access_token": "token_xyz"})

    client = HttpClient(allow_private_ips=True)
    resp = await client.post(
        httpserver.url_for("/oauth/token"),
        data={"grant_type": "client_credentials", "client_id": "service_app"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"access_token": "token_xyz"}
    await client.close()


@pytest.mark.asyncio
async def test_integration_network_error_connection_refused() -> None:
    # Port 59999 is closed locally; hitting it exercises real OS socket rejection
    fast_backoff = HttpBackoffHandler(
        max_retries=1,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.02)],
    )
    client = HttpClient(backoff_handler=fast_backoff, allow_private_ips=True)
    with pytest.raises(HttpNetworkError) as exc_info:
        await client.get("http://127.0.0.1:59999/unreachable")

    assert "unreachable" in exc_info.value.url
    await client.close()


@pytest.mark.asyncio
async def test_integration_timeout_error_translation(httpserver: HTTPServer) -> None:
    def delayed_handler(request: Request) -> Response:
        time.sleep(0.3)
        return Response("slow response")

    httpserver.expect_request("/slow-endpoint").respond_with_handler(delayed_handler)

    client = HttpClient(allow_private_ips=True)
    with pytest.raises(HttpTimeoutError) as exc_info:
        await client.get(httpserver.url_for("/slow-endpoint"), timeout=0.05)

    assert exc_info.value.kind in (TimeoutKind.READ, TimeoutKind.CONNECT)
    await client.close()
