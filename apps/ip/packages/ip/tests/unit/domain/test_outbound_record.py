"""Unit tests for OutboundRecord traced domain aggregate root."""

from __future__ import annotations

import json

from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.dispatch.events import OutboundRecordCreatedEvent
from ip.engine.domain.dispatch.outbound_record import OutboundRecord, compute_request_sha256
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
