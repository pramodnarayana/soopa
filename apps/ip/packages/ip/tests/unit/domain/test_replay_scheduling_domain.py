"""Unit tests for ReplicaRecord normalization replay scheduling and OutboundRecord delivery retry cloning."""

from __future__ import annotations

from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundDispatchStatus,
)
from ip.engine.domain.dispatch.events import OutboundRecordCreatedEvent
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.replication.events import ReplicaRecordChangedEvent
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.domain.trace.enums import (
    IpTraceEventType,
    PipelineStage,
    TraceEventStatus,
)
from ip.engine.domain.trace.trace_event import IpTraceEvent


def test_replica_record_schedule_normalization_replay_emits_changed_event() -> None:
    replica = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="records_alpha",
        primary_key_values=("REC-100",),
        data={"record_id": "REC-100", "quantity": 42.5},
        trace_id="ip_trc_root",
        correlation_id="REC-100",
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
    assert rep_trace_evt.stage == PipelineStage.REPLICA
    assert rep_trace_evt.status == TraceEventStatus.RETRIED

    assert len(replica.domain_events) == 1
    dom_evt = replica.domain_events[0]
    assert isinstance(dom_evt, ReplicaRecordChangedEvent)
    assert dom_evt.trace_id == "ip_trc_norm_replay1"
    assert dom_evt.parent_trace_id == "ip_trc_root"
    assert dom_evt.original_trace_id == "ip_trc_root"
    assert dom_evt.replay_count == 1


def test_outbound_record_clone_for_delivery_retry_resets_delivery_state() -> None:
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
    assert out_trace_evt.stage == PipelineStage.DELIVER
    assert out_trace_evt.status == TraceEventStatus.RETRIED

    assert len(cloned.domain_events) == 1
    dom_evt = cloned.domain_events[0]
    assert isinstance(dom_evt, OutboundRecordCreatedEvent)
    assert dom_evt.record_id == "ip_out_replay1"
    assert dom_evt.trace_id == "ip_trc_deliv_replay1"
    assert dom_evt.replay_count == 1
