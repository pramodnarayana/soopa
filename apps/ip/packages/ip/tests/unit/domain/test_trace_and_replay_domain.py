"""Unit tests for TracedAggregateRoot replay cloning and lineage invariants across L1, L2, L3, and L5."""

from __future__ import annotations

from ip.engine.domain.enums import (
    HttpWriteOperation,
    IngestionMode,
    IpTraceEventType,
    OutboundDispatchStatus,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import (
    InboundRecordCreatedEvent,
    NormalizedRecordCreatedEvent,
    OutboundRecordCreatedEvent,
    ReplicaRecordChangedEvent,
)
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.models.timeline_entry import IpTraceEvent


def test_inbound_record_clone_for_replay_preserves_lineage_and_clears_external_event_id() -> None:
    original = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="itron_mdm",
        stream_name="meter_reads",
        payload_bytes=b'{"meter_id":"MTR-100","kwh":42.5}',
        is_inlined=True,
        trace_id="ip_trc_root",
        correlation_id="MTR-100",
        ingestion_mode=IngestionMode.PUSH_FULL,
        external_event_id="evt_webhook_123",
        request_body={"meter_id": "MTR-100", "kwh": 42.5},
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
    assert cloned.correlation_id == "MTR-100"
    assert cloned.external_event_id is None
    assert cloned.request_body == {"meter_id": "MTR-100", "kwh": 42.5}

    assert len(cloned.trace_events) == 1
    trace_evt = cloned.trace_events[0]
    assert isinstance(trace_evt, IpTraceEvent)
    assert trace_evt.event_type == IpTraceEventType.REPLAY_TRIGGERED.value
    assert trace_evt.actor == "support@soopa.io"
    assert trace_evt.layer == PipelineLayer.L1_INGEST
    assert trace_evt.status == TimelineStatus.RETRIED

    assert len(cloned.domain_events) == 1
    dom_evt = cloned.domain_events[0]
    assert isinstance(dom_evt, InboundRecordCreatedEvent)
    assert dom_evt.record_id == "ip_inb_replay1"
    assert dom_evt.trace_id == "ip_trc_replay1"
    assert dom_evt.parent_trace_id == "ip_trc_root"
    assert dom_evt.original_trace_id == "ip_trc_root"
    assert dom_evt.replay_count == 1

    # Chained replay (Attempt #2) preserves original_trace_id == ip_trc_root
    cloned_2 = cloned.clone_for_replay(
        new_id="ip_inb_replay2",
        new_trace_id="ip_trc_replay2",
        modified_request_body={"meter_id": "MTR-100", "kwh": 99.0},
        actor="support@soopa.io",
    )
    assert cloned_2.parent_trace_id == "ip_trc_replay1"
    assert cloned_2.original_trace_id == "ip_trc_root"
    assert cloned_2.replay_count == 2
    assert cloned_2.request_body == {"meter_id": "MTR-100", "kwh": 99.0}
    assert cloned_2.trace_events[0].event_type == IpTraceEventType.MODIFIED_AND_REPLAYED.value


def test_replica_record_schedule_normalization_replay_emits_changed_event() -> None:
    replica = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meter_reads",
        primary_key_values=("MTR-100",),
        data={"meter_id": "MTR-100", "kwh": 42.5},
        trace_id="ip_trc_root",
        correlation_id="MTR-100",
    )
    replica.clear_domain_events()
    replica.clear_trace_events()

    new_trace_id = replica.schedule_normalization_replay(
        new_trace_id="ip_trc_norm_replay1",
        actor="ops@soopa.io",
    )

    assert new_trace_id == "ip_trc_norm_replay1"
    assert replica.trace_id == "ip_trc_norm_replay1"
    assert replica.parent_trace_id == "ip_trc_root"
    assert replica.original_trace_id == "ip_trc_root"
    assert replica.replay_count == 1

    assert len(replica.trace_events) == 1
    rep_trace_evt = replica.trace_events[0]
    assert isinstance(rep_trace_evt, IpTraceEvent)
    assert rep_trace_evt.event_type == IpTraceEventType.REPLAY_TRIGGERED.value
    assert rep_trace_evt.layer == PipelineLayer.L2_REPLICA
    assert rep_trace_evt.status == TimelineStatus.RETRIED

    assert len(replica.domain_events) == 1
    dom_evt = replica.domain_events[0]
    assert isinstance(dom_evt, ReplicaRecordChangedEvent)
    assert dom_evt.trace_id == "ip_trc_norm_replay1"
    assert dom_evt.parent_trace_id == "ip_trc_root"
    assert dom_evt.original_trace_id == "ip_trc_root"
    assert dom_evt.replay_count == 1


def test_normalized_record_clone_for_replay_supports_payload_modification() -> None:
    norm = NormalizedRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        canonical_type="mdm.meter_reading",
        source_id="MTR-100",
        canonical_data={"meter_id": "MTR-100", "reading_kwh": 42.5},
        trace_id="ip_trc_root",
        correlation_id="MTR-100",
    )

    replayed = norm.clone_for_replay(
        new_id="ip_nrm_replay1",
        new_trace_id="ip_trc_stitch_replay1",
        modified_canonical_data={"meter_id": "MTR-100", "reading_kwh": 55.0},
        actor="engineer@soopa.io",
    )

    assert replayed.id == "ip_nrm_replay1"
    assert replayed.trace_id == "ip_trc_stitch_replay1"
    assert replayed.parent_trace_id == "ip_trc_root"
    assert replayed.original_trace_id == "ip_trc_root"
    assert replayed.replay_count == 1
    assert replayed.canonical_data == {"meter_id": "MTR-100", "reading_kwh": 55.0}
    nrm_trace_evt = replayed.trace_events[0]
    assert isinstance(nrm_trace_evt, IpTraceEvent)
    assert nrm_trace_evt.event_type == IpTraceEventType.MODIFIED_AND_REPLAYED.value
    assert nrm_trace_evt.layer == PipelineLayer.L3_NORMALIZE

    assert len(replayed.domain_events) == 1
    dom_evt = replayed.domain_events[0]
    assert isinstance(dom_evt, NormalizedRecordCreatedEvent)
    assert dom_evt.trace_id == "ip_trc_stitch_replay1"
    assert dom_evt.parent_trace_id == "ip_trc_root"
    assert dom_evt.original_trace_id == "ip_trc_root"
    assert dom_evt.replay_count == 1


def test_outbound_record_clone_for_delivery_retry_resets_status_and_idempotency_key() -> None:
    outbound = OutboundRecord.create_pending(
        tenant_id="ten_01",
        connection_id="conn_dest_01",
        app_id="netsuite_erp",
        stream_name="invoices",
        target_url="https://api.netsuite.example.com/v1/invoices",
        http_method="POST",
        payload_bytes=b'{"invoice_no":"INV-99"}',
        is_inlined=True,
        trace_id="ip_trc_root",
        operation=HttpWriteOperation.CREATE.value,
        idempotency_key="ip_trc_root:invoices:CREATE",
        correlation_id="INV-99",
        request_body={"invoice_no": "INV-99"},
    )
    outbound.mark_failed(
        error_message="HTTP 500 Internal Server Error",
        response_status_code=500,
        failure_category="TERMINAL",
    )

    cloned = outbound.clone_for_delivery_retry(
        new_id="ip_out_replay1",
        new_trace_id="ip_trc_deliv_replay1",
        actor="ops@soopa.io",
    )

    assert cloned.id == "ip_out_replay1"
    assert cloned.trace_id == "ip_trc_deliv_replay1"
    assert cloned.parent_trace_id == "ip_trc_root"
    assert cloned.original_trace_id == "ip_trc_root"
    assert cloned.replay_count == 1
    assert cloned.status == OutboundDispatchStatus.PENDING
    assert cloned.attempt_number == 1
    assert cloned.error_message is None
    assert cloned.failure_category is None
    assert cloned.response_status_code is None
    assert cloned.idempotency_key == "ip_trc_deliv_replay1:invoices:CREATE"

    assert len(cloned.trace_events) == 1
    out_trace_evt = cloned.trace_events[0]
    assert isinstance(out_trace_evt, IpTraceEvent)
    assert out_trace_evt.event_type == IpTraceEventType.REPLAY_TRIGGERED.value
    assert out_trace_evt.layer == PipelineLayer.L5_DELIVER
    assert out_trace_evt.status == TimelineStatus.RETRIED

    assert len(cloned.domain_events) == 1
    dom_evt = cloned.domain_events[0]
    assert isinstance(dom_evt, OutboundRecordCreatedEvent)
    assert dom_evt.record_id == "ip_out_replay1"
    assert dom_evt.trace_id == "ip_trc_deliv_replay1"
    assert dom_evt.replay_count == 1
