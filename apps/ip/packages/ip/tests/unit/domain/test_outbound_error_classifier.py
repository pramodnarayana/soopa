"""Pure zero-mock domain unit tests for Layer-5 HTTP error classification and Retry-After parsing."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.domain.dispatch.classifier import (
    classify_outbound_http_outcome,
    parse_retry_after_seconds,
)
from ip.engine.domain.dispatch.enums import (
    FailureDisposition,
    OutboundConflictStrategy,
    OutboundFailureCategory,
)


def test_parse_retry_after_seconds_from_delta_header() -> None:
    fixed_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after_seconds({"Retry-After": "45"}, now=fixed_now) == 45
    assert parse_retry_after_seconds({"Retry-After": "99999"}, now=fixed_now) == 3600


def test_parse_retry_after_seconds_from_http_date_header() -> None:
    fixed_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
    assert (
        parse_retry_after_seconds(
            {"retry-after": "Mon, 26 Oct 2026 12:01:30 GMT"},
            now=fixed_now,
        )
        == 90
    )


def test_parse_retry_after_seconds_from_ratelimit_reset_epoch() -> None:
    fixed_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
    future_epoch = str(int(fixed_now.timestamp()) + 120)
    assert (
        parse_retry_after_seconds(
            {"X-RateLimit-Reset": future_epoch},
            now=fixed_now,
        )
        == 120
    )


def test_classify_outbound_http_outcome_marks_2xx_successful() -> None:
    ok_res = classify_outbound_http_outcome(201)
    assert ok_res.is_success is True
    assert ok_res.failure_category is None


def test_classify_outbound_http_outcome_treats_idempotent_409_as_success() -> None:
    idem_409 = classify_outbound_http_outcome(
        409,
        conflict_strategy=OutboundConflictStrategy.IDEMPOTENT_SUCCESS,
    )
    assert idem_409.is_success is True
    assert idem_409.failure_category is OutboundFailureCategory.CONFLICT_IDEMPOTENT
    assert idem_409.disposition is FailureDisposition.IGNORE


def test_classify_outbound_http_outcome_fails_non_idempotent_409() -> None:
    fail_409 = classify_outbound_http_outcome(
        409,
        conflict_strategy=OutboundConflictStrategy.FAIL,
    )
    assert fail_409.is_success is False
    assert fail_409.failure_category is OutboundFailureCategory.VALIDATION_ERROR
    assert fail_409.disposition is FailureDisposition.FAIL


def test_classify_outbound_http_outcome_schedules_retry_for_429_rate_limit() -> None:
    rate_res = classify_outbound_http_outcome(429, headers={"Retry-After": "20"})
    assert rate_res.is_success is False
    assert rate_res.failure_category is OutboundFailureCategory.RATE_LIMITED
    assert rate_res.disposition is FailureDisposition.RETRY
    assert rate_res.retry_after_seconds == 20


def test_classify_outbound_http_outcome_marks_401_auth_expired() -> None:
    auth_res = classify_outbound_http_outcome(401)
    assert auth_res.is_success is False
    assert auth_res.failure_category is OutboundFailureCategory.AUTH_EXPIRED
    assert auth_res.disposition is FailureDisposition.FAIL


def test_classify_outbound_http_outcome_schedules_retry_for_5xx_or_network_error() -> None:
    transient_res = classify_outbound_http_outcome(503, headers={"Retry-After": "10"})
    assert transient_res.is_success is False
    assert transient_res.failure_category is OutboundFailureCategory.TRANSIENT
    assert transient_res.disposition is FailureDisposition.RETRY
    assert transient_res.retry_after_seconds == 10

    net_res = classify_outbound_http_outcome(None)
    assert net_res.is_success is False
    assert net_res.failure_category is OutboundFailureCategory.TRANSIENT
    assert net_res.disposition is FailureDisposition.RETRY


def test_classify_outbound_http_outcome_marks_422_validation_error() -> None:
    val_res = classify_outbound_http_outcome(422)
    assert val_res.is_success is False
    assert val_res.failure_category is OutboundFailureCategory.VALIDATION_ERROR
    assert val_res.disposition is FailureDisposition.FAIL


def test_classify_outbound_http_outcome_marks_404_terminal_failure() -> None:
    term_res = classify_outbound_http_outcome(404)
    assert term_res.is_success is False
    assert term_res.failure_category is OutboundFailureCategory.TERMINAL
    assert term_res.disposition is FailureDisposition.FAIL
