"""Unit tests for InboundRecord domain aggregate root."""

from __future__ import annotations

import json

from ip.domain.events import InboundRecordCreatedEvent
from ip.domain.models.inbound_record import (
    InboundRecord,
    compute_payload_sha256,
)


def test_inbound_record_create_inline() -> None:
    data = {"meter_id": "MTR-101", "reading": 450.5}
    payload_bytes = json.dumps(data).encode("utf-8")

    record = InboundRecord.create(
        tenant_id="ten_test_123",
        connection_id="ip_conn_abc",
        stream_name="readings",
        payload_bytes=payload_bytes,
        is_inlined=True,
        raw_payload=data,
        s3_key=None,
        headers={"content-type": "application/json"},
        business_correlation_id="CORR-999",
    )

    assert record.id.startswith("ip_inb_")
    assert record.business_trace_id.startswith("ip_trc_")
    assert record.tenant_id == "ten_test_123"
    assert record.connection_id == "ip_conn_abc"
    assert record.stream_name == "readings"
    assert record.raw_payload == data
    assert record.s3_key is None
    assert record.payload_size_bytes == len(payload_bytes)
    assert record.payload_sha256 == compute_payload_sha256(payload_bytes)
    assert record.headers["content-type"] == "application/json"
    assert record.business_correlation_id == "CORR-999"

    # Verify Domain Event emission
    assert len(record.domain_events) == 1
    event = record.domain_events[0]
    assert isinstance(event, InboundRecordCreatedEvent)
    assert event.record_id == record.id
    assert event.business_trace_id == record.business_trace_id
    assert event.tenant_id == "ten_test_123"
    assert event.is_inlined is True
    assert event.s3_key is None
    assert event.event_name == "ip.inbound_record.created"


def test_inbound_record_create_s3_offloaded() -> None:
    large_payload = b"X" * (70 * 1024)  # 70 KB
    s3_key = "s3://ip-payloads/ten_1/trace_1.json"

    record = InboundRecord.create(
        tenant_id="ten_1",
        connection_id="ip_conn_xyz",
        stream_name="bulk_meters",
        payload_bytes=large_payload,
        is_inlined=False,
        raw_payload=None,
        s3_key=s3_key,
    )

    assert record.raw_payload is None
    assert record.s3_key == s3_key
    assert record.payload_size_bytes == len(large_payload)

    assert len(record.domain_events) == 1
    event = record.domain_events[0]
    assert isinstance(event, InboundRecordCreatedEvent)
    assert event.is_inlined is False
    assert event.s3_key == s3_key
