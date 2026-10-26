"""Pure domain service for Layer-5 outbound HTTP error classification, Retry-After parsing, and header redaction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ip.engine.domain.constants import (
    MAX_RETRY_AFTER_SECONDS,
    REDACTED_SECRET_VALUE,
    SENSITIVE_HTTP_HEADERS,
)
from ip.engine.domain.enums import (
    FailureDisposition,
    OutboundConflictStrategy,
    OutboundFailureCategory,
)
from seedwork.domain.types import JsonDict


@dataclass(frozen=True)
class OutboundHttpClassification:
    """Structured classification of an outbound HTTP response or transport failure."""

    is_success: bool
    failure_category: OutboundFailureCategory | None
    disposition: FailureDisposition | None
    retry_after_seconds: int | None = None


def redact_sensitive_headers(
    headers: Mapping[str, object] | None,
    extra_sensitive_names: Iterable[str] | None = None,
) -> JsonDict:
    """Case-insensitively masks sensitive authentication/cookie headers before audit persistence."""
    if not headers:
        return {}
    extra_set = (
        {n.strip().lower() for n in extra_sensitive_names if n and n.strip()}
        if extra_sensitive_names
        else set()
    )
    redacted: JsonDict = {}
    for key, value in headers.items():
        key_lower = key.strip().lower()
        if key_lower in SENSITIVE_HTTP_HEADERS or key_lower in extra_set:
            redacted[key] = REDACTED_SECRET_VALUE
        else:
            redacted[key] = str(value) if not isinstance(value, (str, int, float, bool)) else value
    return redacted


def _get_header_case_insensitive(headers: Mapping[str, object], target: str) -> str | None:
    target_lower = target.lower()
    for key, val in headers.items():
        val_str = str(val).strip() if val is not None else ""
        if key.lower() == target_lower and val_str:
            return val_str
    return None


def parse_retry_after_seconds(
    headers: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> int | None:
    """Extracts a bounded wait duration in seconds from `Retry-After` or `X-RateLimit-Reset` headers.

    Supports both RFC 7231 integer delta-seconds (e.g. `Retry-After: 30`) and HTTP-date
    timestamps (e.g. `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT`), as well as epoch/delta
    values in `X-RateLimit-Reset` / `RateLimit-Reset`.
    """
    if not headers:
        return None

    reference_now = now or datetime.now(UTC)

    retry_after_raw = _get_header_case_insensitive(headers, "retry-after")
    if retry_after_raw is not None:
        try:
            delta_sec = int(float(retry_after_raw))
            return max(1, min(delta_sec, MAX_RETRY_AFTER_SECONDS))
        except (ValueError, OverflowError):
            try:
                parsed_dt = parsedate_to_datetime(retry_after_raw)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=UTC)
                diff = int((parsed_dt - reference_now).total_seconds())
                return max(1, min(diff, MAX_RETRY_AFTER_SECONDS))
            except (TypeError, ValueError, OverflowError):
                pass

    reset_raw = _get_header_case_insensitive(
        headers, "x-ratelimit-reset"
    ) or _get_header_case_insensitive(headers, "ratelimit-reset")
    if reset_raw is not None:
        try:
            val = float(reset_raw)
            now_epoch = reference_now.timestamp()
            # Values > 1_000_000_000 represent UTC epoch timestamps; smaller values are delta-seconds
            delta = int(val - now_epoch) if val > 1_000_000_000 else int(val)
            return max(1, min(delta, MAX_RETRY_AFTER_SECONDS))
        except (ValueError, OverflowError):
            pass

    return None


def classify_outbound_http_outcome(
    status_code: int | None,
    *,
    headers: Mapping[str, object] | None = None,
    conflict_strategy: OutboundConflictStrategy = OutboundConflictStrategy.FAIL,
    now: datetime | None = None,
) -> OutboundHttpClassification:
    """Deterministically classifies an outbound HTTP response or network failure."""
    if status_code is None:
        return OutboundHttpClassification(
            is_success=False,
            failure_category=OutboundFailureCategory.TRANSIENT,
            disposition=FailureDisposition.RETRY,
            retry_after_seconds=None,
        )

    if 200 <= status_code < 300:
        return OutboundHttpClassification(
            is_success=True,
            failure_category=None,
            disposition=None,
            retry_after_seconds=None,
        )

    if status_code == 409 and conflict_strategy == OutboundConflictStrategy.IDEMPOTENT_SUCCESS:
        return OutboundHttpClassification(
            is_success=True,
            failure_category=OutboundFailureCategory.CONFLICT_IDEMPOTENT,
            disposition=FailureDisposition.IGNORE,
            retry_after_seconds=None,
        )

    if status_code == 429:
        retry_after = parse_retry_after_seconds(headers, now=now)
        return OutboundHttpClassification(
            is_success=False,
            failure_category=OutboundFailureCategory.RATE_LIMITED,
            disposition=FailureDisposition.RETRY,
            retry_after_seconds=retry_after,
        )

    if status_code in (401, 403):
        return OutboundHttpClassification(
            is_success=False,
            failure_category=OutboundFailureCategory.AUTH_EXPIRED,
            disposition=FailureDisposition.FAIL,
            retry_after_seconds=None,
        )

    if status_code in (408, 500, 502, 503, 504):
        retry_after = parse_retry_after_seconds(headers, now=now)
        return OutboundHttpClassification(
            is_success=False,
            failure_category=OutboundFailureCategory.TRANSIENT,
            disposition=FailureDisposition.RETRY,
            retry_after_seconds=retry_after,
        )

    if status_code in (400, 409, 422):
        return OutboundHttpClassification(
            is_success=False,
            failure_category=OutboundFailureCategory.VALIDATION_ERROR,
            disposition=FailureDisposition.FAIL,
            retry_after_seconds=None,
        )

    return OutboundHttpClassification(
        is_success=False,
        failure_category=OutboundFailureCategory.TERMINAL,
        disposition=FailureDisposition.FAIL,
        retry_after_seconds=None,
    )


__all__ = [
    "OutboundHttpClassification",
    "classify_outbound_http_outcome",
    "parse_retry_after_seconds",
    "redact_sensitive_headers",
]
