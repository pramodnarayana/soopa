"""Pluggable Backoff Strategies for HTTP requests inspired by Airbyte CDK."""

from __future__ import annotations

import email.utils
import random
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx


class BackoffStrategy(Protocol):
    """Abstract protocol for computing delay before retrying a failed HTTP request."""

    def compute_backoff(
        self,
        attempt: int,
        response: httpx.Response | None,
        exception: Exception | None,
    ) -> float | None:
        """Calculates backoff duration in seconds. Returns None if strategy does not apply."""
        ...


class HeaderWaitTimeStrategy:
    """Extracts wait time from standard rate-limiting headers (Retry-After, X-RateLimit-Reset)."""

    def __init__(self, max_wait_seconds: float = 300.0) -> None:
        self._max_wait_seconds = max_wait_seconds

    def compute_backoff(
        self,
        attempt: int,
        response: httpx.Response | None,
        exception: Exception | None,
    ) -> float | None:
        if response is None:
            return None

        # 1. Inspect 'Retry-After' header (RFC 7231)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            # Case A: Integer delay in seconds
            try:
                seconds = float(retry_after)
                return min(max(0.0, seconds), self._max_wait_seconds)
            except ValueError:
                pass

            # Case B: HTTP-date format (e.g. 'Wed, 21 Oct 2026 07:28:00 GMT')
            try:
                target_dt = email.utils.parsedate_to_datetime(retry_after)
                if target_dt is not None:
                    now = datetime.now(UTC)
                    wait_seconds = (target_dt - now).total_seconds()
                    return min(max(0.0, wait_seconds), self._max_wait_seconds)
            except (TypeError, ValueError):
                pass

        # 2. Inspect 'X-RateLimit-Reset' header (epoch timestamp)
        reset_header = response.headers.get("X-RateLimit-Reset")
        if reset_header:
            try:
                reset_epoch = float(reset_header)
                now_epoch = time.time()
                wait_seconds = reset_epoch - now_epoch
                return min(max(0.0, wait_seconds), self._max_wait_seconds)
            except ValueError:
                pass

        return None


class ExponentialBackoffStrategy:
    """Computes exponential backoff delay with randomized jitter: min(max_delay, factor * 2^attempt + jitter)."""

    def __init__(
        self,
        factor: float = 1.0,
        max_delay: float = 60.0,
        jitter_ratio: float = 0.25,
    ) -> None:
        self._factor = factor
        self._max_delay = max_delay
        self._jitter_ratio = jitter_ratio

    def compute_backoff(
        self,
        attempt: int,
        response: httpx.Response | None,
        exception: Exception | None,
    ) -> float | None:
        base_delay = self._factor * (2**attempt)
        jitter = random.uniform(0.0, base_delay * self._jitter_ratio)  # noqa: S311 - Jitter randomization for rate limiting, not cryptographic
        total_delay = base_delay + jitter
        return min(total_delay, self._max_delay)
