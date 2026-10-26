"""Pure zero-mock domain unit tests for Layer-5 error classification, Retry-After parsing, and header redaction."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.domain.constants import REDACTED_SECRET_VALUE
from ip.engine.domain.enums import (
    FailureDisposition,
    OutboundConflictStrategy,
    OutboundDispatchStatus,
    OutboundFailureCategory,
)
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.services.outbound_error_classifier import (
    classify_outbound_http_outcome,
    parse_retry_after_seconds,
    redact_sensitive_headers,
)


def test_redact_sensitive_headers_masks_auth_and_cookies_case_insensitively() -> None:
    raw_headers: dict[str, object] = {
        "Authorization": "Bearer super_secret_jwt",
        "x-api-key": "key_12345",
        "Set-Cookie": "session=xyz",
        "Content-Type": "application/json",
        "Idempotency-Key": "idem-999",
    }
    redacted = redact_sensitive_headers(raw_headers)

    assert redacted["Authorization"] == REDACTED_SECRET_VALUE
    assert redacted["x-api-key"] == REDACTED_SECRET_VALUE
    assert redacted["Set-Cookie"] == REDACTED_SECRET_VALUE
    assert redacted["Content-Type"] == "application/json"
    assert redacted["Idempotency-Key"] == "idem-999"


def test_outbound_record_automatically_redacts_headers_in_all_lifecycle_transitions() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="conn_1",
        app_id="sap_isu",
        stream_name="meter_readings",
        operation="UPSERT",
        idempotency_key="idem_key_1",
        external_record_id="MTR-100",
        target_url="https://sap.example.com/api/readings",
        http_method="PUT",
        payload_bytes=b'{"kwh": 42.5}',
        is_inlined=True,
        trace_id="trc_1",
        request_headers={
            "Authorization": "Bearer secret_token",
            "Idempotency-Key": "idem_key_1",
        },
        request_body={"kwh": 42.5},
    )
    assert record.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert record.request_headers["Idempotency-Key"] == "idem_key_1"
    assert record.operation == "UPSERT"
    assert record.idempotency_key == "idem_key_1"
    assert record.external_record_id == "MTR-100"

    record.schedule_retry(
        error_message="HTTP 429 Too Many Requests",
        next_attempt=2,
        response_status_code=429,
        response_headers={"Retry-After": "30", "Set-Cookie": "secret_cookie"},
        failure_category=OutboundFailureCategory.RATE_LIMITED.value,
        retry_after_seconds=30,
    )
    assert record.status == OutboundDispatchStatus.RETRY_SCHEDULED
    assert record.failure_category == OutboundFailureCategory.RATE_LIMITED.value
    assert record.retry_after_seconds == 30
    assert record.response_headers is not None
    assert record.response_headers["Set-Cookie"] == REDACTED_SECRET_VALUE
    assert record.response_headers["Retry-After"] == "30"

    delivered_record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="con_1",
        app_id="sap_isu",
        stream_name="meters",
        target_url="https://erp.example.com/api/meters",
        http_method="POST",
        request_headers={},
        payload_bytes=b"{}",
        is_inlined=True,
        trace_id="ip_trc_2",
    )
    delivered_record.mark_delivered(
        response_status_code=200,
        response_headers={"X-Auth-Token": "tok_999", "X-Request-Id": "req_1"},
        response_body={"id": "SAP-900"},
        duration_ms=55,
        external_record_id="SAP-900",
    )
    assert delivered_record.status == OutboundDispatchStatus.DELIVERED
    assert delivered_record.external_record_id == "SAP-900"
    assert delivered_record.failure_category is None
    assert delivered_record.retry_after_seconds is None
    assert delivered_record.response_headers is not None
    assert delivered_record.response_headers["X-Auth-Token"] == REDACTED_SECRET_VALUE
    assert delivered_record.response_headers["X-Request-Id"] == "req_1"


def test_parse_retry_after_seconds_supports_delta_http_date_and_ratelimit_reset() -> None:
    fixed_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)

    # 1. Integer delta-seconds
    assert parse_retry_after_seconds({"Retry-After": "45"}, now=fixed_now) == 45

    # 2. RFC 7231 HTTP-date (90 seconds in the future)
    assert (
        parse_retry_after_seconds(
            {"retry-after": "Mon, 26 Oct 2026 12:01:30 GMT"},
            now=fixed_now,
        )
        == 90
    )

    # 3. X-RateLimit-Reset as UTC epoch timestamp (120 seconds in the future)
    future_epoch = str(int(fixed_now.timestamp()) + 120)
    assert (
        parse_retry_after_seconds(
            {"X-RateLimit-Reset": future_epoch},
            now=fixed_now,
        )
        == 120
    )

    # 4. Clamping upper bound to MAX_RETRY_AFTER_SECONDS (3600)
    assert parse_retry_after_seconds({"Retry-After": "99999"}, now=fixed_now) == 3600


def test_classify_outbound_http_outcome_all_categories() -> None:
    # 201 Created -> Success
    ok_res = classify_outbound_http_outcome(201)
    assert ok_res.is_success is True
    assert ok_res.failure_category is None

    # 409 Conflict with IDEMPOTENT_SUCCESS -> Success
    idem_409 = classify_outbound_http_outcome(
        409,
        conflict_strategy=OutboundConflictStrategy.IDEMPOTENT_SUCCESS,
    )
    assert idem_409.is_success is True
    assert idem_409.failure_category is OutboundFailureCategory.CONFLICT_IDEMPOTENT
    assert idem_409.disposition is FailureDisposition.IGNORE

    # 409 Conflict with default FAIL -> Validation Error
    fail_409 = classify_outbound_http_outcome(
        409,
        conflict_strategy=OutboundConflictStrategy.FAIL,
    )
    assert fail_409.is_success is False
    assert fail_409.failure_category is OutboundFailureCategory.VALIDATION_ERROR
    assert fail_409.disposition is FailureDisposition.FAIL

    # 429 Too Many Requests with Retry-After -> RATE_LIMITED + RETRY
    rate_res = classify_outbound_http_outcome(429, headers={"Retry-After": "20"})
    assert rate_res.is_success is False
    assert rate_res.failure_category is OutboundFailureCategory.RATE_LIMITED
    assert rate_res.disposition is FailureDisposition.RETRY
    assert rate_res.retry_after_seconds == 20

    # 401 Unauthorized -> AUTH_EXPIRED
    auth_res = classify_outbound_http_outcome(401)
    assert auth_res.is_success is False
    assert auth_res.failure_category is OutboundFailureCategory.AUTH_EXPIRED
    assert auth_res.disposition is FailureDisposition.FAIL

    # 503 Service Unavailable -> TRANSIENT + RETRY
    transient_res = classify_outbound_http_outcome(503, headers={"Retry-After": "10"})
    assert transient_res.is_success is False
    assert transient_res.failure_category is OutboundFailureCategory.TRANSIENT
    assert transient_res.disposition is FailureDisposition.RETRY
    assert transient_res.retry_after_seconds == 10

    # Network error -> TRANSIENT + RETRY
    net_res = classify_outbound_http_outcome(None)
    assert net_res.is_success is False
    assert net_res.failure_category is OutboundFailureCategory.TRANSIENT
    assert net_res.disposition is FailureDisposition.RETRY

    # 422 Unprocessable Entity -> VALIDATION_ERROR + FAIL
    val_res = classify_outbound_http_outcome(422)
    assert val_res.is_success is False
    assert val_res.failure_category is OutboundFailureCategory.VALIDATION_ERROR
    assert val_res.disposition is FailureDisposition.FAIL

    # 404 Not Found -> TERMINAL + FAIL
    term_res = classify_outbound_http_outcome(404)
    assert term_res.is_success is False
    assert term_res.failure_category is OutboundFailureCategory.TERMINAL
    assert term_res.disposition is FailureDisposition.FAIL
