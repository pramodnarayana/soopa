"""Unit tests for HTTP resilience, backoff strategies, and retry handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from shttp.exceptions import HttpTimeoutError, TimeoutKind
from shttp.resilience import (
    ExponentialBackoffStrategy,
    HeaderWaitTimeStrategy,
    HttpBackoffHandler,
)


def test_header_wait_time_strategy_integer_seconds() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=60.0)
    response = httpx.Response(
        status_code=429,
        headers={"Retry-After": "12"},
        request=httpx.Request("GET", "https://api.example.com"),
    )
    delay = strategy.compute_backoff(0, response, None)
    assert delay == 12.0


def test_header_wait_time_strategy_max_delay_cap() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=30.0)
    response = httpx.Response(
        status_code=429,
        headers={"Retry-After": "120"},
        request=httpx.Request("GET", "https://api.example.com"),
    )
    delay = strategy.compute_backoff(0, response, None)
    assert delay == 30.0


def test_header_wait_time_strategy_http_date() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=300.0)
    future_time = datetime.now(UTC) + timedelta(seconds=15)
    # Format according to RFC 7231
    date_str = future_time.strftime("%a, %d %b %Y %H:%M:%S GMT")
    response = httpx.Response(
        status_code=429,
        headers={"Retry-After": date_str},
        request=httpx.Request("GET", "https://api.example.com"),
    )
    delay = strategy.compute_backoff(0, response, None)
    assert delay is not None
    assert 13.0 <= delay <= 16.0


def test_header_wait_time_strategy_rate_limit_reset() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=300.0)
    reset_epoch = (datetime.now(UTC) + timedelta(seconds=20)).timestamp()
    response = httpx.Response(
        status_code=429,
        headers={"X-RateLimit-Reset": str(reset_epoch)},
        request=httpx.Request("GET", "https://api.example.com"),
    )
    delay = strategy.compute_backoff(0, response, None)
    assert delay is not None
    assert 18.0 <= delay <= 22.0


def test_header_wait_time_strategy_no_headers() -> None:
    strategy = HeaderWaitTimeStrategy()
    response = httpx.Response(
        status_code=429,
        request=httpx.Request("GET", "https://api.example.com"),
    )
    assert strategy.compute_backoff(0, response, None) is None
    assert strategy.compute_backoff(0, None, None) is None


def test_exponential_backoff_strategy() -> None:
    strategy = ExponentialBackoffStrategy(factor=1.0, max_delay=10.0, jitter_ratio=0.1)
    # attempt 0: base 1.0, jitter up to 0.1
    delay_0 = strategy.compute_backoff(0, None, None)
    assert delay_0 is not None
    assert 1.0 <= delay_0 <= 1.1

    # attempt 2: base 4.0, jitter up to 0.4
    delay_2 = strategy.compute_backoff(2, None, None)
    assert delay_2 is not None
    assert 4.0 <= delay_2 <= 4.4

    # attempt 5: base 32.0, capped to max_delay 10.0
    delay_5 = strategy.compute_backoff(5, None, None)
    assert delay_5 == 10.0


@pytest.mark.asyncio
async def test_http_backoff_handler_success_no_retry() -> None:
    handler = HttpBackoffHandler(max_retries=3)
    call_count = 0

    async def request_fn() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, request=httpx.Request("GET", "https://api.example.com"))

    resp = await handler.execute(request_fn, method="GET")
    assert resp.status_code == 200
    assert call_count == 1


@pytest.mark.asyncio
async def test_http_backoff_handler_retry_on_429() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.1)],
    )
    call_count = 0

    async def request_fn() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, request=httpx.Request("GET", "https://api.example.com"))
        return httpx.Response(200, request=httpx.Request("GET", "https://api.example.com"))

    resp = await handler.execute(request_fn, method="GET")
    assert resp.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_http_backoff_handler_retries_exhausted() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.05)],
    )
    call_count = 0

    async def request_fn() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, request=httpx.Request("GET", "https://api.example.com"))

    resp = await handler.execute(request_fn, method="GET")
    assert resp.status_code == 503
    assert call_count == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_http_backoff_handler_network_timeout_retry() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.05)],
    )
    call_count = 0

    async def request_fn() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("Timed out reading data")
        return httpx.Response(200, request=httpx.Request("GET", "https://api.example.com"))

    resp = await handler.execute(request_fn, method="GET")
    assert resp.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_http_backoff_handler_network_timeout_retries_exhausted_raises_timeout_error() -> (
    None
):
    handler = HttpBackoffHandler(
        max_retries=1,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.05)],
    )

    async def request_fn() -> httpx.Response:
        raise httpx.ReadTimeout("Timed out reading data")

    with pytest.raises(HttpTimeoutError) as exc_info:
        await handler.execute(request_fn, method="GET")

    assert exc_info.value.kind == TimeoutKind.READ
    assert exc_info.value.classify().value == "TIMEOUT"


@pytest.mark.asyncio
async def test_http_backoff_handler_non_idempotent_post_not_retried_on_500() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=[ExponentialBackoffStrategy(factor=0.01, max_delay=0.05)],
    )
    call_count = 0

    async def request_fn() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, request=httpx.Request("POST", "https://api.example.com"))

    resp = await handler.execute(request_fn, method="POST")
    assert resp.status_code == 500
    assert call_count == 1  # Not retried for non-idempotent POST


@pytest.mark.asyncio
async def test_http_backoff_handler_non_idempotent_post_retried_on_429() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=[HeaderWaitTimeStrategy(max_wait_seconds=0.01)],
    )
    call_count = 0

    async def request_fn() -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                request=httpx.Request("POST", "https://api.example.com"),
            )
        return httpx.Response(200, request=httpx.Request("POST", "https://api.example.com"))

    resp = await handler.execute(request_fn, method="POST")
    assert resp.status_code == 200
    assert call_count == 2
