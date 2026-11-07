"""Unit tests for InboundRecord and NormalizedRecord replay cloning invariants."""

from __future__ import annotations

from ip.engine.domain.normalization.events import NormalizedRecordCreatedEvent
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.replication.enums import IngestionMode
from ip.engine.domain.replication.events import InboundRecordCreatedEvent
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.trace.enums import (
    IpTraceEventType,
    PipelineStage,
    TraceEventStatus,
)
from ip.engine.domain.trace.trace_event import IpTraceEvent


def test_inbound_record_clone_for_replay_preserves_lineage_without_external_event_id() -> None:
    original = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-100","quantity":42.5}',
        is_inlined=True,
        trace_id="ip_trc_root",
        correlation_id="REC-100",
        ingestion_mode=IngestionMode.PUSH_FULL,
        external_event_id="evt_webhook_123",
        request_body={"record_id": "REC-100", "quantity": 42.5},
    )

    cloned = original.clone_for_replay(
        new_id="ip_inb_replay1",
        new_trace_id="ip_trc_replay1",
        actor="support@soopa.io",
    )

    assert cloned.id == "ip_inb_replay1"
    assert cloned.trace_id == "ip_trc_replay1"
    assert cloned.parent_trace_id == "ip_trc_root"
    assert cloned.original_trace_id == "ip_trc_root"
    assert cloned.replay_count == 1
    assert cloned.correlation_id == "REC-100"
    assert cloned.external_event_id is None
    assert cloned.request_body == {"record_id": "REC-100", "quantity": 42.5}

    assert len(cloned.trace_events) == 1
    trace_evt = cloned.trace_events[0]
    assert isinstance(trace_evt, IpTraceEvent)
    assert trace_evt.event_type == IpTraceEventType.REPLAY_TRIGGERED.value
    assert trace_evt.actor == "support@soopa.io"
    assert trace_evt.stage == PipelineStage.INGEST
    assert trace_evt.status == TraceEventStatus.RETRIED

    assert len(cloned.domain_events) == 1
    dom_evt = cloned.domain_events[0]
    assert isinstance(dom_evt, InboundRecordCreatedEvent)
    assert dom_evt.record_id == "ip_inb_replay1"
    assert dom_evt.trace_id == "ip_trc_replay1"
    assert dom_evt.parent_trace_id == "ip_trc_root"
    assert dom_evt.original_trace_id == "ip_trc_root"
    assert dom_evt.replay_count == 1


def test_inbound_record_chained_replay_retains_root_original_trace_id() -> None:
    original = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-100","quantity":42.5}',
        is_inlined=True,
        trace_id="ip_trc_root",
        correlation_id="REC-100",
        ingestion_mode=IngestionMode.PUSH_FULL,
        request_body={"record_id": "REC-100", "quantity": 42.5},
    )
    cloned_1 = original.clone_for_replay(
        new_id="ip_inb_replay1",
        new_trace_id="ip_trc_replay1",
        actor="support@soopa.io",
    )
    cloned_2 = cloned_1.clone_for_replay(
        new_id="ip_inb_replay2",
        new_trace_id="ip_trc_replay2",
        modified_request_body={"record_id": "REC-100", "quantity": 99.0},
        actor="support@soopa.io",
    )
    assert cloned_2.parent_trace_id == "ip_trc_replay1"
    assert cloned_2.original_trace_id == "ip_trc_root"
    assert cloned_2.replay_count == 2
    assert cloned_2.request_body == {"record_id": "REC-100", "quantity": 99.0}
    assert cloned_2.trace_events[0].event_type == IpTraceEventType.MODIFIED_AND_REPLAYED.value


def test_normalized_record_clone_for_replay_applies_modified_canonical_data() -> None:
    norm = NormalizedRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        canonical_type="canonical.record_alpha",
        source_id="REC-100",
        canonical_data={"record_id": "REC-100", "normalized_quantity": 42.5},
        trace_id="ip_trc_root",
        correlation_id="REC-100",
    )

    replayed = norm.clone_for_replay(
        new_id="ip_nrm_replay1",
        new_trace_id="ip_trc_stitch_replay1",
        modified_canonical_data={"record_id": "REC-100", "normalized_quantity": 55.0},
        actor="engineer@soopa.io",
    )

    assert replayed.id == "ip_nrm_replay1"
    assert replayed.trace_id == "ip_trc_stitch_replay1"
    assert replayed.parent_trace_id == "ip_trc_root"
    assert replayed.original_trace_id == "ip_trc_root"
    assert replayed.replay_count == 1
    assert replayed.canonical_data == {"record_id": "REC-100", "normalized_quantity": 55.0}
    nrm_trace_evt = replayed.trace_events[0]
    assert isinstance(nrm_trace_evt, IpTraceEvent)
    assert nrm_trace_evt.event_type == IpTraceEventType.MODIFIED_AND_REPLAYED.value
    assert nrm_trace_evt.stage == PipelineStage.NORMALIZE

    assert len(replayed.domain_events) == 1
    dom_evt = replayed.domain_events[0]
    assert isinstance(dom_evt, NormalizedRecordCreatedEvent)
    assert dom_evt.trace_id == "ip_trc_stitch_replay1"
    assert dom_evt.parent_trace_id == "ip_trc_root"
    assert dom_evt.original_trace_id == "ip_trc_root"
    assert dom_evt.replay_count == 1
