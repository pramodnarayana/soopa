"""Unit tests for InboundRecord traced domain aggregate root."""

from __future__ import annotations

import json

from ip.engine.domain.events import InboundRecordCreatedEvent
from ip.engine.domain.models.inbound_record import (
    InboundRecord,
    compute_payload_sha256,
)
from seedwork.domain.types import JsonDict
from seedwork.models import TracedAggregateRoot


def test_inbound_record_create_inline() -> None:
    data: JsonDict = {"meter_id": "MTR-101", "reading": 450.5}
    payload_bytes = json.dumps(data).encode("utf-8")

    record = InboundRecord.create(
        tenant_id="ten_test_123",
        connection_id="ip_conn_abc",
        app_id="itron_mdm",
        stream_name="readings",
        payload_bytes=payload_bytes,
        is_inlined=True,
        request_body=data,
        request_s3_key=None,
        request_headers={"content-type": "application/json"},
        response_status_code=202,
        correlation_id="CORR-999",
        parent_trace_id="ip_trc_parent",
        original_trace_id="ip_trc_orig",
        replay_count=1,
    )

    assert isinstance(record, TracedAggregateRoot)
    assert record.id.startswith("ip_inb_")
    assert record.trace_id.startswith("ip_trc_")
    assert record.tenant_id == "ten_test_123"
    assert record.connection_id == "ip_conn_abc"
    assert record.app_id == "itron_mdm"
    assert record.stream_name == "readings"
    assert record.request_body == data
    assert record.request_s3_key is None
    assert record.request_size_bytes == len(payload_bytes)
    assert record.request_sha256 == compute_payload_sha256(payload_bytes)
    assert record.request_headers["content-type"] == "application/json"
    assert record.response_status_code == 202
    assert record.correlation_id == "CORR-999"
    assert record.parent_trace_id == "ip_trc_parent"
    assert record.original_trace_id == "ip_trc_orig"
    assert record.replay_count == 1
    assert len(record.trace_events) == 1
    assert record.trace_events[0].trace_id == record.trace_id

    # Verify Domain Event emission
    assert len(record.domain_events) == 1
    event = record.domain_events[0]
    assert isinstance(event, InboundRecordCreatedEvent)
    assert event.record_id == record.id
    assert event.trace_id == record.trace_id
    assert event.correlation_id == "CORR-999"
    assert event.parent_trace_id == "ip_trc_parent"
    assert event.original_trace_id == "ip_trc_orig"
    assert event.replay_count == 1
    assert event.tenant_id == "ten_test_123"
    assert event.app_id == "itron_mdm"
    assert event.is_inlined is True
    assert event.s3_key is None
    assert event.event_name == "ip.inbound_record.created"


def test_inbound_record_create_s3_offloaded() -> None:
    large_payload = b"X" * (70 * 1024)  # 70 KB
    s3_key = "s3://ip-payloads/ten_1/trace_1.json"

    record = InboundRecord.create(
        tenant_id="ten_1",
        connection_id="ip_conn_xyz",
        app_id="itron_mdm",
        stream_name="bulk_meters",
        payload_bytes=large_payload,
        is_inlined=False,
        request_body=None,
        request_s3_key=s3_key,
    )

    assert record.request_body is None
    assert record.request_s3_key == s3_key
    assert record.request_size_bytes == len(large_payload)

    assert len(record.domain_events) == 1
    event = record.domain_events[0]
    assert isinstance(event, InboundRecordCreatedEvent)
    assert event.is_inlined is False
    assert event.s3_key == s3_key
