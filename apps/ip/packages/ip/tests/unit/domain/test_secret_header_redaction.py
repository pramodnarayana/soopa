"""Pure zero-mock domain unit tests for sensitive HTTP header redaction in OutboundRecord."""

from __future__ import annotations

from ip.engine.domain.constants import REDACTED_SECRET_VALUE
from ip.engine.domain.dispatch.classifier import redact_sensitive_headers
from ip.engine.domain.dispatch.enums import OutboundDispatchStatus, OutboundFailureCategory
from ip.engine.domain.dispatch.outbound_record import OutboundRecord


def test_redact_sensitive_headers_masks_credentials_case_insensitively() -> None:
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


def test_outbound_record_create_pending_redacts_request_headers() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="conn_1",
        app_id="partner_erp",
        stream_name="records_alpha",
        operation="UPSERT",
        idempotency_key="idem_key_1",
        external_record_id="REC-100",
        target_url="https://erp.example.com/api/records",
        http_method="PUT",
        payload_bytes=b'{"metric_value": 42.5}',
        is_inlined=True,
        trace_id="trc_1",
        request_headers={
            "Authorization": "Bearer secret_token",
            "Idempotency-Key": "idem_key_1",
        },
        request_body={"metric_value": 42.5},
    )
    assert record.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert record.request_headers["Idempotency-Key"] == "idem_key_1"
    assert record.operation == "UPSERT"
    assert record.idempotency_key == "idem_key_1"
    assert record.external_record_id == "REC-100"


def test_outbound_record_schedule_retry_redacts_response_headers() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="conn_1",
        app_id="partner_erp",
        stream_name="records_alpha",
        target_url="https://erp.example.com/api/records",
        http_method="PUT",
        payload_bytes=b'{"metric_value": 42.5}',
        is_inlined=True,
        trace_id="trc_1",
        request_headers={},
    )
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


def test_outbound_record_mark_delivered_redacts_response_headers() -> None:
    delivered_record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="con_1",
        app_id="partner_erp",
        stream_name="records_beta",
        target_url="https://erp.example.com/api/records_beta",
        http_method="POST",
        request_headers={},
        payload_bytes=b"{}",
        is_inlined=True,
        trace_id="ip_trc_2",
    )
    delivered_record.mark_delivered(
        response_status_code=200,
        response_headers={"X-Auth-Token": "tok_999", "X-Request-Id": "req_1"},
        response_body={"id": "ERP-900"},
        duration_ms=55,
        external_record_id="ERP-900",
    )
    assert delivered_record.status == OutboundDispatchStatus.DELIVERED
    assert delivered_record.external_record_id == "ERP-900"
    assert delivered_record.failure_category is None
    assert delivered_record.retry_after_seconds is None
    assert delivered_record.response_headers is not None
    assert delivered_record.response_headers["X-Auth-Token"] == REDACTED_SECRET_VALUE
    assert delivered_record.response_headers["X-Request-Id"] == "req_1"
