"""Unit tests for InboundRecord traced domain aggregate root."""

from __future__ import annotations

import json

from ip.engine.domain.replication.events import InboundRecordCreatedEvent
from ip.engine.domain.replication.inbound_record import (
    InboundBatchItemSpec,
    InboundRecord,
    compute_payload_sha256,
)
from seedwork.domain.types import JsonDict
from seedwork.events import EventProcessingLane
from strace.domain import TracedAggregateRoot


def test_inbound_record_create_inline() -> None:
    data: JsonDict = {"record_id": "REC-101", "reading": 450.5}
    payload_bytes = json.dumps(data).encode("utf-8")

    record = InboundRecord.create(
        tenant_id="ten_test_123",
        connection_id="ip_conn_abc",
        app_id="acme_source",
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
    assert record.app_id == "acme_source"
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
    assert event.app_id == "acme_source"
    assert event.is_inlined is True
    assert event.s3_key is None
    assert event.event_name == "ip.inbound_record.created"


def test_inbound_record_create_s3_offloaded() -> None:
    large_payload = b"X" * (70 * 1024)  # 70 KB
    s3_key = "s3://ip-payloads/ten_1/trace_1.json"

    record = InboundRecord.create(
        tenant_id="ten_1",
        connection_id="ip_conn_xyz",
        app_id="acme_source",
        stream_name="bulk_records",
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


def test_inbound_record_create_assigns_batch_metadata() -> None:
    body: JsonDict = {"id": "ORD-1", "total": 99.0}
    raw = json.dumps(body).encode("utf-8")

    record = InboundRecord.create(
        tenant_id="ten_batch_1",
        connection_id="ip_conn_01",
        app_id="crm_source",
        stream_name="orders",
        payload_bytes=raw,
        is_inlined=True,
        request_body=body,
        causation_depth=1,
    )

    assert record.batch_id.startswith("ip_bch_")
    assert record.batch_seq == 0
    assert record.causation_depth == 1
    event = record.domain_events[0]
    assert isinstance(event, InboundRecordCreatedEvent)
    assert event.batch_id == record.batch_id
    assert event.range_start == record.id
    assert event.range_end == record.id
    assert event.count == 1
    assert event.causation_depth == 1
    assert event.get_processing_lane() == EventProcessingLane.REALTIME


def test_inbound_record_create_range_batch_emits_single_range_claim_check() -> None:
    items = [
        InboundBatchItemSpec(
            payload_bytes=json.dumps({"id": f"ORD-{idx}"}).encode("utf-8"),
            is_inlined=True,
            request_body={"id": f"ORD-{idx}"},
            external_event_id=f"ext_{idx}",
        )
        for idx in range(3)
    ]

    records = InboundRecord.create_range_batch(
        tenant_id="ten_batch_range",
        connection_id="ip_conn_bulk",
        app_id="erp_source",
        stream_name="invoices",
        items=items,
    )

    assert len(records) == 3
    assert [r.batch_seq for r in records] == [0, 1, 2]
    assert len({r.batch_id for r in records}) == 1
    assert records[0].batch_id.startswith("ip_bch_")
    assert records[0].id < records[1].id < records[2].id
    assert all(len(r.trace_events) == 1 for r in records)

    all_domain_events = [evt for r in records for evt in r.domain_events]
    assert len(all_domain_events) == 1
    assert len(records[0].domain_events) == 1
    assert len(records[1].domain_events) == 0
    assert len(records[2].domain_events) == 0

    claim_check = all_domain_events[0]
    assert isinstance(claim_check, InboundRecordCreatedEvent)
    assert claim_check.batch_id == records[0].batch_id
    assert claim_check.range_start == records[0].id
    assert claim_check.range_end == records[2].id
    assert claim_check.count == 3
    assert claim_check.record_ids == ()
    assert claim_check.get_processing_lane() == EventProcessingLane.BULK
