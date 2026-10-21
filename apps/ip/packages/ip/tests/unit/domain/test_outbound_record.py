"""Unit tests for OutboundRecord domain aggregate root."""

from __future__ import annotations

import json

from ip.domain.events import OutboundRecordCreatedEvent
from ip.domain.models.outbound_record import (
    OutboundDispatchStatus,
    OutboundRecord,
    compute_request_sha256,
)


def test_outbound_record_create_pending() -> None:
    data = {"shipment_id": "SHP-1234", "carrier": "FedEx"}
    payload_bytes = json.dumps(data).encode("utf-8")

    record = OutboundRecord.create_pending(
        tenant_id="ten_transport_1",
        connection_id="ip_conn_mercury_gate",
        app_id="mercurygate",
        stream_name="shipments",
        target_url="https://mercurygate.carrier.net/api/v1/shipments",
        http_method="POST",
        payload_bytes=payload_bytes,
        is_inlined=True,
        business_trace_id="ip_trc_9988",
        business_correlation_id="TXN-901",
        request_headers={"Content-Type": "application/json"},
        request_body=data,
    )

    assert record.id.startswith("ip_out_")
    assert record.tenant_id == "ten_transport_1"
    assert record.connection_id == "ip_conn_mercury_gate"
    assert record.app_id == "mercurygate"
    assert record.stream_name == "shipments"
    assert record.target_url == "https://mercurygate.carrier.net/api/v1/shipments"
    assert record.http_method == "POST"
    assert record.status == OutboundDispatchStatus.PENDING
    assert record.request_body == data
    assert record.request_s3_key is None
    assert record.request_size_bytes == len(payload_bytes)
    assert record.request_sha256 == compute_request_sha256(payload_bytes)
    assert record.attempt_number == 1
    assert record.response_status_code is None

    # Verify Domain Event emission
    assert len(record.domain_events) == 1
    event = record.domain_events[0]
    assert isinstance(event, OutboundRecordCreatedEvent)
    assert event.record_id == record.id
    assert event.app_id == "mercurygate"
    assert event.status == OutboundDispatchStatus.PENDING
    assert event.event_name == "ip.outbound_record.created"


def test_outbound_record_state_transitions() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="ten_1",
        connection_id="ip_conn_1",
        app_id="itron_mdm",
        stream_name="meters",
        target_url="https://ami.gridpower.com/api/v1/meters",
        http_method="POST",
        payload_bytes=b'{"id": "1"}',
        is_inlined=True,
        business_trace_id="ip_trc_1",
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
    assert record.status == OutboundDispatchStatus.DELIVERED
    assert record.response_status_code == 200
    assert record.response_body == {"destination_id": "DEST-888"}
    assert record.duration_ms == 45
    assert record.error_message is None

    # 3. Simulate failure
    record.mark_failed(error_message="401 Unauthorized", response_status_code=401)
    assert record.status == OutboundDispatchStatus.FAILED
    assert record.error_message == "401 Unauthorized"
    assert record.response_status_code == 401
