"""Resilient HTTP request execution handler with rate-limit and transient backoff recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

import httpx
import structlog

from ..exceptions import HttpError, HttpNetworkError, HttpTimeoutError, TimeoutKind
from .backoff_strategy import (
    BackoffStrategy,
    ExponentialBackoffStrategy,
    HeaderWaitTimeStrategy,
)

logger = structlog.get_logger(__name__)

DEFAULT_TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

IDEMPOTENT_HTTP_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

PRE_SEND_NETWORK_EXCEPTIONS = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.PoolTimeout,
)

TRANSIENT_NETWORK_EXCEPTIONS = (
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    OSError,
)


def _safe_get_url(response: httpx.Response | None) -> str:
    if response is None:
        return ""
    try:
        return str(response.url)
    except RuntimeError:
        return ""


def _map_network_exception(exc: BaseException, url: str = "") -> HttpError:
    if isinstance(exc, httpx.ConnectTimeout):
        return HttpTimeoutError(str(exc), url=url, kind=TimeoutKind.CONNECT, cause=exc)
    if isinstance(exc, httpx.ReadTimeout):
        return HttpTimeoutError(str(exc), url=url, kind=TimeoutKind.READ, cause=exc)
    if isinstance(exc, httpx.WriteTimeout):
        return HttpTimeoutError(str(exc), url=url, kind=TimeoutKind.WRITE, cause=exc)
    if isinstance(exc, httpx.PoolTimeout):
        return HttpTimeoutError(str(exc), url=url, kind=TimeoutKind.POOL, cause=exc)
    return HttpNetworkError(str(exc), url=url, cause=exc)


class HttpBackoffHandler:
    """Executes asynchronous HTTP requests with configurable resilience policies and retry loops."""

    def __init__(
        self,
        max_retries: int = 3,
        strategies: Sequence[BackoffStrategy] | None = None,
        transient_status_codes: frozenset[int] = DEFAULT_TRANSIENT_STATUS_CODES,
    ) -> None:
        self._max_retries = max_retries
        self._strategies = strategies or (
            HeaderWaitTimeStrategy(),
            ExponentialBackoffStrategy(),
        )
        self._transient_status_codes = transient_status_codes

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def _determine_backoff(
        self,
        attempt: int,
        response: httpx.Response | None,
        exception: Exception | None,
    ) -> float:
        for strategy in self._strategies:
            wait_time = strategy.compute_backoff(attempt, response, exception)
            if wait_time is not None:
                return wait_time
        return 1.0

    async def execute(
        self,
        request_fn: Callable[[], Awaitable[httpx.Response]],
        url: str = "",
        method: str = "GET",
    ) -> httpx.Response:
        """Executes an asynchronous request callable, retrying transient faults with backoff."""
        is_idempotent = method.upper() in IDEMPOTENT_HTTP_METHODS
        attempt = 0
        while True:
            response: httpx.Response | None = None
            try:
                response = await request_fn()
                if response.status_code not in self._transient_status_codes:
                    return response

                # Non-idempotent methods are only retried on 429 rate limit or 503 with explicit Retry-After
                if not is_idempotent:
                    is_safe_retry = response.status_code == 429 or (
                        response.status_code == 503 and bool(response.headers.get("Retry-After"))
                    )
                    if not is_safe_retry:
                        return response

                if attempt >= self._max_retries:
                    logger.error(
                        "http_request_retries_exhausted",
                        status_code=response.status_code,
                        attempts=attempt + 1,
                        url=_safe_get_url(response) or url,
                    )
                    return response

                wait_time = self._determine_backoff(attempt, response, None)
                logger.warning(
                    "http_transient_status_retrying",
                    status_code=response.status_code,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    wait_seconds=round(wait_time, 2),
                    url=_safe_get_url(response) or url,
                )
                await asyncio.sleep(wait_time)
                attempt += 1

            except TRANSIENT_NETWORK_EXCEPTIONS as exc:
                # For non-idempotent methods, only pre-send connection failures are safe to retry
                if not is_idempotent and not isinstance(exc, PRE_SEND_NETWORK_EXCEPTIONS):
                    logger.error(
                        "http_non_idempotent_post_send_failure_not_retried",
                        method=method,
                        error=str(exc),
                        url=url,
                    )
                    raise _map_network_exception(exc, url=url) from exc

                if attempt >= self._max_retries:
                    logger.error(
                        "http_network_retries_exhausted",
                        error=str(exc),
                        attempts=attempt + 1,
                        url=url,
                    )
                    raise _map_network_exception(exc, url=url) from exc

                wait_time = self._determine_backoff(attempt, None, exc)
                logger.warning(
                    "http_network_exception_retrying",
                    error=str(exc),
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    wait_seconds=round(wait_time, 2),
                    url=url,
                )
                await asyncio.sleep(wait_time)
                attempt += 1
            except httpx.TransportError as exc:
                raise _map_network_exception(exc, url=url) from exc
