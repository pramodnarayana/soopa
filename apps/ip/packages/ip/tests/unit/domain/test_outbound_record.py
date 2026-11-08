"""Unit tests for OutboundRecord traced domain aggregate root."""

from __future__ import annotations

import json

from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.dispatch.events import OutboundRecordCreatedEvent
from ip.engine.domain.dispatch.outbound_record import OutboundRecord, compute_request_sha256
from ip.engine.domain.dispatch.quarantine_record import QuarantineRecord
from seedwork.domain.types import JsonDict
from strace.domain import TracedAggregateRoot


def test_outbound_record_create_pending() -> None:
    data: JsonDict = {"order_id": "ORD-1234", "partner": "Acme"}
    payload_bytes = json.dumps(data).encode("utf-8")

    record = OutboundRecord.create_pending(
        tenant_id="ten_partner_1",
        connection_id="ip_conn_dest",
        app_id="acme_destination",
        stream_name="orders",
        target_url="https://api.destination.example.com/api/v1/orders",
        http_method="POST",
        payload_bytes=payload_bytes,
        is_inlined=True,
        trace_id="ip_trc_9988",
        correlation_id="TXN-901",
        request_headers={"Content-Type": "application/json"},
        request_body=data,
    )

    assert isinstance(record, TracedAggregateRoot)
    assert record.id.startswith("ip_out_")
    assert record.tenant_id == "ten_partner_1"
    assert record.trace_id == "ip_trc_9988"
    assert record.correlation_id == "TXN-901"
    assert record.connection_id == "ip_conn_dest"
    assert record.app_id == "acme_destination"
    assert record.stream_name == "orders"
    assert record.target_url == "https://api.destination.example.com/api/v1/orders"
    assert record.http_method == "POST"
    assert record.status == OutboundDispatchStatus.PENDING
    assert record.request_body == data
    assert record.request_s3_key is None
    assert record.request_size_bytes == len(payload_bytes)
    assert record.request_sha256 == compute_request_sha256(payload_bytes)
    assert record.attempt_number == 1
    assert record.response_status_code is None
    assert len(record.trace_events) == 1

    # Verify Domain Event emission
    assert len(record.domain_events) == 1
    event = record.domain_events[0]
    assert isinstance(event, OutboundRecordCreatedEvent)
    assert event.record_id == record.id
    assert event.trace_id == "ip_trc_9988"
    assert event.app_id == "acme_destination"
    assert event.status == OutboundDispatchStatus.PENDING
    assert event.event_name == "ip.outbound_record.created"


def test_outbound_record_state_transitions() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="ip_conn_1",
        app_id="acme_source",
        stream_name="records_alpha",
        target_url="https://api.partner.example.com/api/v1/records_alpha",
        http_method="POST",
        payload_bytes=b'{"id": "1"}',
        is_inlined=True,
        trace_id="ip_trc_1",
    )

    # 1. Simulate transient failure with retry schedule
    record.schedule_retry(error_message="Gateway timeout", next_attempt=2, response_status_code=504)
    assert record.status == OutboundDispatchStatus.RETRY_SCHEDULED
    assert record.attempt_number == 2
    assert record.response_status_code == 504
    assert record.error_message == "Gateway timeout"

    # 2. Simulate successful delivery
    record.mark_delivered(
        response_status_code=200,
        response_body={"destination_id": "DEST-888"},
        duration_ms=45,
    )
    assert record.status.value == OutboundDispatchStatus.DELIVERED.value
    assert record.response_status_code == 200
    assert record.response_body == {"destination_id": "DEST-888"}
    assert record.duration_ms == 45
    assert record.error_message is None

    # 3. Simulate failure
    record.mark_failed(error_message="401 Unauthorized", response_status_code=401)
    assert record.status.value == OutboundDispatchStatus.FAILED.value
    assert record.error_message == "401 Unauthorized"
    assert record.response_status_code == 401
    assert len(record.trace_events) == 4


def test_outbound_record_mark_in_flight_attempt_sets_in_flight_without_domain_event() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="ip_conn_1",
        app_id="acme_source",
        stream_name="records_alpha",
        target_url="https://api.partner.example.com/api/v1/records_alpha",
        http_method="POST",
        payload_bytes=b'{"id": "1"}',
        is_inlined=True,
        trace_id="ip_trc_in_flight",
    )
    record.clear_domain_events()

    record.mark_in_flight_attempt(attempt_number=2)

    assert record.status is OutboundDispatchStatus.IN_FLIGHT
    assert record.attempt_number == 2
    assert len(record.domain_events) == 0


def test_outbound_record_mark_rate_limited_preserves_attempt_budget() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="ip_conn_1",
        app_id="acme_source",
        stream_name="records_alpha",
        target_url="https://api.partner.example.com/api/v1/records_alpha",
        http_method="POST",
        payload_bytes=b'{"id": "1"}',
        is_inlined=True,
        trace_id="ip_trc_rl",
    )
    record.mark_in_flight_attempt(attempt_number=1)

    record.mark_rate_limited(
        error_message="HTTP 429 Too Many Requests",
        retry_after_seconds=30,
        response_status_code=429,
    )

    assert record.status is OutboundDispatchStatus.RATE_LIMITED
    assert record.attempt_number == 1
    assert record.retry_after_seconds == 30


def test_quarantine_record_create_captures_terminal_failure_metadata() -> None:
    qrn = QuarantineRecord.create(
        tenant_id="ten_1",
        connection_id="ip_conn_1",
        outbound_record_id="ip_out_1",
        stream_name="records_alpha",
        idempotency_key="idem_1",
        trace_id="ip_trc_qrn",
        correlation_id="REC-1",
        failure_category="VALIDATION_ERROR",
        error_code="HTTP_ERROR",
        error_message="Invalid schema",
        response_status_code=422,
        attempt_count=1,
        request_body={"id": "REC-1"},
        response_body={"detail": "Invalid schema"},
    )

    assert qrn.id.startswith("ip_qrn_")
    assert qrn.tenant_id == "ten_1"
    assert qrn.outbound_record_id == "ip_out_1"
    assert qrn.failure_category == "VALIDATION_ERROR"
    assert qrn.response_status_code == 422
    assert qrn.attempt_count == 1
