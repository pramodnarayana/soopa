"""Unit tests for HTTP resilience, backoff strategies, and retry handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from shttp.resilience import (
    ExponentialBackoffStrategy,
    HeaderWaitTimeStrategy,
    HttpBackoffHandler,
)


def test_header_wait_time_strategy_integer_seconds() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=60.0)
    response = httpx.Response(status_code=429, headers={"Retry-After": "15"})
    wait_time = strategy.compute_backoff(attempt=0, response=response, exception=None)
    assert wait_time == 15.0


def test_header_wait_time_strategy_caps_max_wait() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=30.0)
    response = httpx.Response(status_code=429, headers={"Retry-After": "120"})
    wait_time = strategy.compute_backoff(attempt=0, response=response, exception=None)
    assert wait_time == 30.0


def test_header_wait_time_strategy_http_date() -> None:
    strategy = HeaderWaitTimeStrategy(max_wait_seconds=300.0)
    future_time = datetime.now(UTC) + timedelta(seconds=20)
    date_str = future_time.strftime("%a, %d %b %Y %H:%M:%S GMT")
    response = httpx.Response(status_code=429, headers={"Retry-After": date_str})
    wait_time = strategy.compute_backoff(attempt=0, response=response, exception=None)
    assert wait_time is not None
    assert 18.0 <= wait_time <= 22.0


def test_header_wait_time_strategy_missing_header_returns_none() -> None:
    strategy = HeaderWaitTimeStrategy()
    response = httpx.Response(status_code=500, headers={})
    assert strategy.compute_backoff(attempt=0, response=response, exception=None) is None
    assert strategy.compute_backoff(attempt=0, response=None, exception=None) is None


def test_exponential_backoff_strategy_progression() -> None:
    strategy = ExponentialBackoffStrategy(factor=1.0, max_delay=10.0, jitter_ratio=0.0)
    delay_0 = strategy.compute_backoff(attempt=0, response=None, exception=None)
    delay_1 = strategy.compute_backoff(attempt=1, response=None, exception=None)
    delay_2 = strategy.compute_backoff(attempt=2, response=None, exception=None)

    assert delay_0 == 1.0
    assert delay_1 == 2.0
    assert delay_2 == 4.0

    delay_high = strategy.compute_backoff(attempt=10, response=None, exception=None)
    assert delay_high == 10.0  # Capped at max_delay


@pytest.mark.asyncio
async def test_http_backoff_handler_success_immediate() -> None:
    handler = HttpBackoffHandler(max_retries=2)
    calls = 0

    async def _request_fn() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code=200, json={"status": "ok"})

    resp = await handler.execute(_request_fn)
    assert resp.status_code == 200
    assert calls == 1


@pytest.mark.asyncio
async def test_http_backoff_handler_non_transient_no_retry() -> None:
    handler = HttpBackoffHandler(max_retries=3)
    calls = 0

    async def _request_fn() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code=400, text="Bad Request")

    resp = await handler.execute(_request_fn)
    assert resp.status_code == 400
    assert calls == 1


@pytest.mark.asyncio
async def test_http_backoff_handler_retry_on_429_success() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=(ExponentialBackoffStrategy(factor=0.01, jitter_ratio=0.0),),
    )
    calls = 0

    async def _request_fn() -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code=429, headers={"Retry-After": "0.01"})
        return httpx.Response(status_code=200, json={"result": "recovered"})

    resp = await handler.execute(_request_fn)
    assert resp.status_code == 200
    assert calls == 2


@pytest.mark.asyncio
async def test_http_backoff_handler_exhausts_retries() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=(ExponentialBackoffStrategy(factor=0.01, jitter_ratio=0.0),),
    )
    calls = 0

    async def _request_fn() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code=503, text="Service Unavailable")

    resp = await handler.execute(_request_fn)
    assert resp.status_code == 503
    assert calls == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_http_backoff_handler_network_timeout_recovers() -> None:
    handler = HttpBackoffHandler(
        max_retries=2,
        strategies=(ExponentialBackoffStrategy(factor=0.01, jitter_ratio=0.0),),
    )
    calls = 0

    async def _request_fn() -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("Connection timed out")
        return httpx.Response(status_code=200, json={"status": "online"})

    resp = await handler.execute(_request_fn)
    assert resp.status_code == 200
    assert calls == 2
