"""Pure unit tests verifying IP Engine DomainEvent routing, trace, and lane contracts."""

from __future__ import annotations

from ip.engine.domain.connection.events import (
    ConnectionActivatedEvent,
    ConnectionCreatedEvent,
    ConnectionDeactivatedEvent,
    ConnectionDeletedEvent,
    ConnectionErrorRecordedEvent,
    ConnectionRelinkedEvent,
)
from ip.engine.domain.dispatch.events import OutboundRecordCreatedEvent
from ip.engine.domain.enums import IpEventType
from ip.engine.domain.normalization.events import (
    CanonicalRecordChangedEvent,
    NormalizedRecordCreatedEvent,
    TransformationChangedEvent,
    TransformationVersionPromotedEvent,
)
from ip.engine.domain.replication.events import (
    FetchRecordRequestedEvent,
    GenerationCompletedEvent,
    InboundRecordCreatedEvent,
    ReplicaRecordChangedEvent,
    StreamStateCheckpointedEvent,
    SyncRunCancelledEvent,
    SyncRunCompletedEvent,
    SyncRunFailedEvent,
    SyncRunRequestedEvent,
    SyncRunStartedEvent,
)
from ip.engine.domain.stitch.events import StitchRegisteredEvent
from ip.engine.domain.stitch.stitch import (
    EmitNotificationStepInput,
    EmitNotificationStepOutput,
    ExecuteHttpActionStepInput,
    QueryReplicaStepInput,
    QueryReplicaStepOutput,
    Stitch,
)
from seedwork.events import EventProcessingLane


def test_replication_domain_events_expose_routing_headers() -> None:
    inb_single = InboundRecordCreatedEvent(
        record_ids=("inb_1",),
        tenant_id="t_1",
        trace_id="tr_1",
        correlation_id="corr_1",
    )
    assert inb_single.record_id == "inb_1"
    assert inb_single.range_start == "inb_1"
    assert inb_single.range_end == "inb_1"
    assert inb_single.event_name == IpEventType.INBOUND_RECORD_CREATED
    assert inb_single.get_routing_tenant_id() == "t_1"
    assert inb_single.get_trace_id() == "tr_1"
    assert inb_single.get_correlation_id() == "corr_1"
    assert inb_single.get_processing_lane() is EventProcessingLane.REALTIME

    inb_bulk = InboundRecordCreatedEvent(
        batch_id="ip_bch_1",
        range_start="inb_0",
        range_end="inb_9",
        count=10,
        tenant_id="t_1",
    )
    assert inb_bulk.record_id == "inb_0"
    assert inb_bulk.get_processing_lane() is EventProcessingLane.BULK

    rep_bulk = ReplicaRecordChangedEvent(
        record_ids=("rep_1", "rep_2"),
        tenant_id="t_1",
        trace_id="tr_rep",
        correlation_id="corr_rep",
    )
    assert rep_bulk.record_id == "rep_1"
    assert rep_bulk.event_name == IpEventType.REPLICA_RECORD_CHANGED
    assert rep_bulk.get_routing_tenant_id() == "t_1"
    assert rep_bulk.get_trace_id() == "tr_rep"
    assert rep_bulk.get_correlation_id() == "corr_rep"
    assert rep_bulk.get_processing_lane() is EventProcessingLane.BULK

    checkpoint = StreamStateCheckpointedEvent(
        state_id="st_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream_name="records",
        cursor_value="cur_9",
        records_synced_count=25,
    )
    assert checkpoint.event_name == IpEventType.STREAM_STATE_CHECKPOINTED
    assert checkpoint.get_routing_tenant_id() == "t_1"

    fetch_bulk = FetchRecordRequestedEvent(
        record_ids=("ext_1", "ext_2"),
        tenant_id="t_1",
        trace_id="tr_f",
        correlation_id="corr_f",
    )
    assert fetch_bulk.record_id == "ext_1"
    assert fetch_bulk.event_name == IpEventType.FETCH_RECORD_REQUESTED
    assert fetch_bulk.get_routing_tenant_id() == "t_1"
    assert fetch_bulk.get_trace_id() == "tr_f"
    assert fetch_bulk.get_correlation_id() == "corr_f"
    assert fetch_bulk.get_processing_lane() is EventProcessingLane.BULK


def test_sync_lifecycle_events_expose_routing_headers() -> None:
    req = SyncRunRequestedEvent(
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        kind="INCREMENTAL",
        trace_id="tr_sync",
        correlation_id="corr_sync",
    )
    assert req.event_name == IpEventType.SYNC_RUN_REQUESTED
    assert req.get_routing_tenant_id() == "t_1"
    assert req.get_trace_id() == "tr_sync"
    assert req.get_correlation_id() == "corr_sync"
    assert req.get_processing_lane() is EventProcessingLane.BULK

    started = SyncRunStartedEvent(
        run_id="r_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        kind="INCREMENTAL",
        generation_id=1,
        start_checkpoint=None,
        trace_id="tr_sync",
    )
    assert started.event_name == IpEventType.SYNC_RUN_STARTED
    assert started.get_routing_tenant_id() == "t_1"
    assert started.get_trace_id() == "tr_sync"

    completed = SyncRunCompletedEvent(
        run_id="r_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        kind="INCREMENTAL",
        generation_id=1,
        end_checkpoint="c_9",
        pages_count=2,
        records_count=20,
        bytes_count=1024,
        trace_id="tr_sync",
    )
    assert completed.event_name == IpEventType.SYNC_RUN_COMPLETED
    assert completed.get_routing_tenant_id() == "t_1"
    assert completed.get_trace_id() == "tr_sync"

    failed = SyncRunFailedEvent(
        run_id="r_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        kind="INCREMENTAL",
        generation_id=1,
        error_code="ERR",
        error_message="failed",
        trace_id="tr_sync",
    )
    assert failed.event_name == IpEventType.SYNC_RUN_FAILED
    assert failed.get_routing_tenant_id() == "t_1"
    assert failed.get_trace_id() == "tr_sync"

    cancelled = SyncRunCancelledEvent(
        run_id="r_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        kind="INCREMENTAL",
        generation_id=1,
        reason="operator",
        trace_id="tr_sync",
    )
    assert cancelled.event_name == IpEventType.SYNC_RUN_CANCELLED
    assert cancelled.get_routing_tenant_id() == "t_1"
    assert cancelled.get_trace_id() == "tr_sync"

    gen = GenerationCompletedEvent(
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        generation_id=2,
        trace_id="tr_gen",
    )
    assert gen.event_name == IpEventType.GENERATION_COMPLETED
    assert gen.get_routing_tenant_id() == "t_1"
    assert gen.get_trace_id() == "tr_gen"
    assert gen.get_processing_lane() is EventProcessingLane.BULK


def test_normalization_dispatch_control_plane_events_expose_routing_headers() -> None:
    norm = NormalizedRecordCreatedEvent(
        record_ids=("norm_1", "norm_2"),
        tenant_id="t_1",
        trace_id="tr_n",
        correlation_id="corr_n",
    )
    assert norm.record_id == "norm_1"
    assert norm.event_name == IpEventType.NORMALIZED_RECORD_CREATED
    assert norm.get_routing_tenant_id() == "t_1"
    assert norm.get_trace_id() == "tr_n"
    assert norm.get_correlation_id() == "corr_n"
    assert norm.get_processing_lane() is EventProcessingLane.BULK

    canon = CanonicalRecordChangedEvent(
        record_ids=("src_1", "src_2"),
        tenant_id="t_1",
        trace_id="tr_c",
        correlation_id="corr_c",
    )
    assert canon.source_id == "src_1"
    assert canon.event_name == IpEventType.CANONICAL_RECORD_CHANGED
    assert canon.get_routing_tenant_id() == "t_1"
    assert canon.get_trace_id() == "tr_c"
    assert canon.get_correlation_id() == "corr_c"
    assert canon.get_processing_lane() is EventProcessingLane.BULK

    tx_changed = TransformationChangedEvent(
        id="tx_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        transformation_id="map_1",
        transformation_version=1,
        mode="ACTIVE",
    )
    assert tx_changed.event_name == IpEventType.TRANSFORMATION_CHANGED
    assert tx_changed.get_routing_tenant_id() == "t_1"
    assert tx_changed.get_processing_lane() is EventProcessingLane.BULK

    tx_promoted = TransformationVersionPromotedEvent(
        id="tx_1",
        tenant_id="t_1",
        connection_id="c_1",
        stream="records",
        transformation_id="map_1",
        promoted_version=2,
        previous_version=1,
    )
    assert tx_promoted.event_name == IpEventType.TRANSFORMATION_VERSION_PROMOTED
    assert tx_promoted.get_routing_tenant_id() == "t_1"
    assert tx_promoted.get_processing_lane() is EventProcessingLane.BULK

    out = OutboundRecordCreatedEvent(
        record_ids=("out_1", "out_2"),
        tenant_id="t_1",
        trace_id="tr_o",
        correlation_id="corr_o",
    )
    assert out.record_id == "out_1"
    assert out.event_name == IpEventType.OUTBOUND_RECORD_CREATED
    assert out.get_routing_tenant_id() == "t_1"
    assert out.get_trace_id() == "tr_o"
    assert out.get_correlation_id() == "corr_o"
    assert out.get_processing_lane() is EventProcessingLane.BULK

    cp_events = (
        ConnectionCreatedEvent("c_1", "t_1", "http", "Conn", "API_KEY"),
        ConnectionActivatedEvent("c_1", "t_1", "http"),
        ConnectionDeactivatedEvent("c_1", "t_1", "http"),
        ConnectionDeletedEvent("c_1", "t_1", "http"),
        ConnectionRelinkedEvent("c_1", "t_1", "http", "2026-10-27T00:00:00Z"),
        ConnectionErrorRecordedEvent("c_1", "t_1", "AUTH", "expired"),
    )
    for evt in cp_events:
        assert evt.event_name != ""
        assert evt.get_routing_tenant_id() == "t_1"

    stitch_evt = StitchRegisteredEvent(
        stitch_id="st_1",
        tenant_id="t_1",
        workflow_id="wf_1",
        workflow_version=1,
        canonical_event_type="canonical.v1",
        is_trigger=True,
        is_active=True,
    )
    assert stitch_evt.event_name == IpEventType.STITCH_REGISTERED
    assert stitch_evt.get_routing_tenant_id() == "t_1"
    assert stitch_evt.get_processing_lane() is EventProcessingLane.BULK


def test_stitch_aggregate_evaluates_filter_conditions() -> None:
    stitch = Stitch(
        id="st_1",
        tenant_id="t_1",
        workflow_id="wf_1",
        workflow_version=1,
        canonical_event_type="canonical.v1",
        is_trigger=True,
        idempotency_key_field="entity_id",
        concurrency_key_field="account_id",
        resource_hint_field="region",
        filter_conditions={"status": "ACTIVE", "tier": 2},
    )
    assert stitch.matches_payload({"status": "ACTIVE", "tier": 2, "entity_id": "ent_1"}) is True
    assert stitch.matches_payload({"status": "INACTIVE", "tier": 2}) is False
    assert (
        stitch.extract_idempotency_key({"entity_id": "ent_9"}, fallback_event_id="ev_1")
        == "wf_1:ent_9"
    )
    assert stitch.extract_idempotency_key({}, fallback_event_id="ev_1") == "wf_1:ev_1"
    assert stitch.extract_concurrency_key({"account_id": "acc_1"}) == "acc_1"
    assert stitch.extract_concurrency_key({}) is None
    assert stitch.extract_resource_hint({"region": "us_east"}) == "us_east"
    assert stitch.extract_resource_hint({}) is None


def test_stitch_step_dto_codecs_validate_payloads() -> None:
    qr_ok = QueryReplicaStepInput.from_payload(
        {"connection_id": "c_1", "stream": "orders", "record_key": "rk_1"}
    )
    assert qr_ok.is_ok
    assert QueryReplicaStepInput.from_payload({"connection_id": ""}).is_err
    qr_out = QueryReplicaStepOutput(found=True, record_id="r_1", version=1, data={"k": "v"})
    assert qr_out.to_payload()["found"] is True

    notif_ok = EmitNotificationStepInput.from_payload(
        {
            "channel": "email",
            "template_id": "tpl_1",
            "recipient": "ops@example.com",
            "variables": {"id": "1"},
        }
    )
    assert notif_ok.is_ok
    assert EmitNotificationStepInput.from_payload({"channel": ""}).is_err
    notif_out = EmitNotificationStepOutput(envelope_id="env_1", event_type="notification.requested")
    assert notif_out.to_payload()["envelope_id"] == "env_1"

    http_ok = ExecuteHttpActionStepInput.from_payload(
        {
            "connection_id": "c_1",
            "stream_name": "orders",
            "operation": "create",
            "payload": {"amount": 42},
            "conflict_strategy": "INVALID_FALLBACK",
            "causation_depth": 2,
        }
    )
    assert http_ok.is_ok
    assert http_ok.unwrap().causation_depth == 2
    assert ExecuteHttpActionStepInput.from_payload({"connection_id": ""}).is_err
    assert ExecuteHttpActionStepInput.from_payload(
        {"connection_id": "c_1", "stream_name": "orders", "operation": "BOGUS"}
    ).is_err
