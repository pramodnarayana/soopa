"""Unit tests for SyncRun state machine, behavioral IP aggregates, and HttpSourceSpec."""

from __future__ import annotations

from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.connection.http_spec import (
    HttpRequestSpec,
    HttpSourceSpec,
    HttpStreamDefinition,
)
from ip.engine.domain.exceptions import InvalidSyncRunStateError, IpErrorCode
from ip.engine.domain.normalization.enums import NormalizationOutcome, TransformationMode
from ip.engine.domain.normalization.events import (
    TransformationChangedEvent,
    TransformationVersionPromotedEvent,
)
from ip.engine.domain.normalization.transformation import Transformation
from ip.engine.domain.replication.enums import (
    IngestionMode,
    MergeOutcome,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.replication.events import (
    FetchRecordRequestedEvent,
    GenerationCompletedEvent,
    ReplicaRecordChangedEvent,
    SyncRunCancelledEvent,
    SyncRunCompletedEvent,
    SyncRunFailedEvent,
    SyncRunStartedEvent,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.domain.replication.stream_definition import StreamDefinition
from ip.engine.domain.replication.sync_run import SyncRun


def test_sync_run_create_initial() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
        start_checkpoint=None,
        trace_id="trc_1",
    )
    assert run.id.startswith("ip_sync_")
    assert run.tenant_id == "tenant_1"
    assert run.connection_id == "conn_1"
    assert run.stream == "invoices"
    assert run.kind == SyncRunKind.INITIAL
    assert run.status == SyncRunStatus.PENDING
    assert run.generation_id == 1
    assert run.pages_synced == 0
    assert run.records_synced == 0
    assert run.bytes_synced == 0
    assert len(run.domain_events) == 0


def test_sync_run_start_transitions_to_running_emitting_started_event() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INCREMENTAL,
        generation_id=2,
        start_checkpoint="2026-10-01T00:00:00Z",
        trace_id="trc_1",
    )
    res = run.start()
    assert res.is_ok
    assert res.unwrap() is run
    assert run.status == SyncRunStatus.RUNNING
    assert run.started_at is not None

    events = run.domain_events
    assert len(events) == 1
    assert isinstance(events[0], SyncRunStartedEvent)
    assert events[0].run_id == run.id
    assert events[0].kind == "INCREMENTAL"
    assert events[0].start_checkpoint == "2026-10-01T00:00:00Z"


def test_sync_run_start_rejects_duplicate_start_on_running_run() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INCREMENTAL,
        generation_id=2,
        start_checkpoint="2026-10-01T00:00:00Z",
        trace_id="trc_1",
    )
    assert run.start().is_ok

    second_res = run.start()
    assert second_res.is_err
    err = second_res.unwrap_err()
    assert isinstance(err, InvalidSyncRunStateError)
    assert err.code == IpErrorCode.INVALID_SYNC_RUN_STATE


def test_sync_run_invalid_transitions_return_result_fail() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
        trace_id="trc_1",
    )
    # Cannot succeed or record_page while still PENDING
    succeed_res = run.succeed()
    assert succeed_res.is_err
    assert succeed_res.unwrap_err().code == IpErrorCode.INVALID_SYNC_RUN_STATE

    complete_res = run.complete()
    assert complete_res.is_err
    assert complete_res.unwrap_err().code == IpErrorCode.INVALID_SYNC_RUN_STATE

    page_res = run.record_page(records_in_page=10, bytes_size=128)
    assert page_res.is_err
    assert page_res.unwrap_err().code == IpErrorCode.INVALID_SYNC_RUN_STATE


def test_sync_run_record_page() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INCREMENTAL,
        generation_id=1,
        trace_id="trc_1",
    )
    assert run.start().is_ok
    assert run.record_page(records_in_page=100, bytes_size=10240, next_checkpoint="c1").is_ok
    assert run.record_page(records_in_page=50, bytes_size=5120, next_checkpoint="c2").is_ok

    assert run.pages_synced == 2
    assert run.records_synced == 150
    assert run.bytes_synced == 15360
    assert run.end_checkpoint == "c2"


def test_sync_run_succeed_full_refresh_emits_generation_completed() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.FULL_REFRESH,
        generation_id=3,
        trace_id="trc_1",
    )
    assert run.start().is_ok
    assert run.record_page(
        records_in_page=200, bytes_size=20480, next_checkpoint="cursor_final"
    ).is_ok
    complete_res = run.complete(end_checkpoint="cursor_final")
    assert complete_res.is_ok

    assert run.status == SyncRunStatus.SUCCEEDED
    assert run.finished_at is not None
    assert run.end_checkpoint == "cursor_final"

    event_types = [type(e) for e in run.domain_events]
    assert SyncRunStartedEvent in event_types
    assert SyncRunCompletedEvent in event_types
    assert GenerationCompletedEvent in event_types

    # Cannot fail or cancel an already succeeded run
    assert run.fail(error_code="ERR", error_message="boom").is_err
    assert run.cancel().is_err


def test_sync_run_fail_transitions_to_failed_once() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
        trace_id="trc_1",
    )
    assert run.start().is_ok
    fail_res = run.fail(
        error_code="RATE_LIMIT_EXCEEDED", error_message="HTTP 429 Too Many Requests"
    )
    assert fail_res.is_ok
    assert run.status == SyncRunStatus.FAILED
    assert run.error_code == "RATE_LIMIT_EXCEEDED"
    assert run.error_message == "HTTP 429 Too Many Requests"

    failed_events = [e for e in run.domain_events if isinstance(e, SyncRunFailedEvent)]
    assert len(failed_events) == 1
    assert failed_events[0].error_code == "RATE_LIMIT_EXCEEDED"

    # Repeated failure transitions on an already-FAILED run are rejected without mutation
    second_fail = run.fail(error_code="OTHER_ERROR", error_message="Should not overwrite")
    assert second_fail.is_err
    assert run.error_code == "RATE_LIMIT_EXCEEDED"
    assert run.error_message == "HTTP 429 Too Many Requests"
    assert len([e for e in run.domain_events if isinstance(e, SyncRunFailedEvent)]) == 1


def test_sync_run_cancel_transitions_pending_run_to_cancelled() -> None:
    pending_run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="orders",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
        trace_id="trc_2",
    )
    cancel_res = pending_run.cancel(reason="Operator cancelled")
    assert cancel_res.is_ok
    assert pending_run.status == SyncRunStatus.CANCELLED
    cancelled_events = [
        e for e in pending_run.domain_events if isinstance(e, SyncRunCancelledEvent)
    ]
    assert len(cancelled_events) == 1
    assert cancelled_events[0].reason == "Operator cancelled"
    assert pending_run.cancel().is_err


def test_inbound_record_request_thin_record_fetch_emits_fetch_event() -> None:
    inbound = InboundRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        app_id="shopify",
        stream_name="orders",
        payload_bytes=b'{"id":"ord_1"}',
        is_inlined=True,
        request_body={"id": "ord_1"},
        ingestion_mode=IngestionMode.PUSH_THIN,
        trace_id="trc_thin",
    )
    inbound.request_thin_record_fetch(record_id="ord_1")
    fetch_events = [e for e in inbound.domain_events if isinstance(e, FetchRecordRequestedEvent)]
    assert len(fetch_events) == 1
    assert fetch_events[0].record_id == "ord_1"
    assert fetch_events[0].notice_inbound_record_id == inbound.id


def test_transformation_promote_shadow_version_activates_candidate() -> None:
    transformation = Transformation.bind(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="orders",
        transformation_id="shopify_orders",
        transformation_version=1,
        mode=TransformationMode.ACTIVE,
        shadow_transformation_version=2,
    )
    assert any(isinstance(e, TransformationChangedEvent) for e in transformation.domain_events)
    transformation.clear_domain_events()

    promo_res = transformation.promote_shadow_version()
    assert promo_res.is_ok
    prev_ver, promoted_ver = promo_res.unwrap()
    assert prev_ver == 1
    assert promoted_ver == 2
    assert transformation.transformation_version == 2
    assert transformation.shadow_transformation_version is None
    assert any(
        isinstance(e, TransformationVersionPromotedEvent) for e in transformation.domain_events
    )

    assert transformation.promote_shadow_version().is_err


def test_replica_record_batch_upsert_chunk_emits_batch_event() -> None:
    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="orders",
        primary_key_values=("ord_1",),
        data={"id": "ord_1"},
        trace_id="trc_rep",
    )
    replica.clear_domain_events()
    replica.clear_trace_events()

    assert not hasattr(replica, "record_normalization_trace")
    assert not hasattr(replica, "record_canonical_change")

    replica.record_batch_upsert_chunk(chunk_record_ids=(replica.id, "ip_rep_2"))
    assert len(replica.domain_events) == 1
    assert isinstance(replica.domain_events[0], ReplicaRecordChangedEvent)
    assert replica.domain_events[0].outcome == MergeOutcome.BATCH_UPSERT.value


def test_http_source_spec_looks_up_stream_by_name() -> None:
    spec = HttpSourceSpec(
        base_url="https://api.example.com",
        auth_type=AuthType.BEARER_TOKEN,
        streams=(
            HttpStreamDefinition(
                request=HttpRequestSpec(path="/orders"),
                replication=StreamDefinition(stream="orders"),
            ),
        ),
    )
    assert spec.get_stream("orders") is not None
    assert spec.get_stream("missing") is None
    assert NormalizationOutcome.NORMALIZED.value == "NORMALIZED"
