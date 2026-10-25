"""Unit tests for SyncRun aggregate root state machine and events."""

from __future__ import annotations

import pytest
from ip.engine.domain.enums import SyncRunKind, SyncRunStatus
from ip.engine.domain.events import (
    GenerationCompletedEvent,
    SyncRunCompletedEvent,
    SyncRunFailedEvent,
    SyncRunStartedEvent,
)
from ip.engine.domain.models.sync_run import SyncRun


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


def test_sync_run_start_emits_event() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INCREMENTAL,
        generation_id=2,
        start_checkpoint="2026-10-01T00:00:00Z",
        trace_id="trc_1",
    )
    run.start()
    assert run.status == SyncRunStatus.RUNNING
    assert run.started_at is not None

    events = run.domain_events
    assert len(events) == 1
    assert isinstance(events[0], SyncRunStartedEvent)
    assert events[0].run_id == run.id
    assert events[0].kind == "INCREMENTAL"
    assert events[0].start_checkpoint == "2026-10-01T00:00:00Z"


def test_sync_run_invalid_transition_raises() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
        trace_id="trc_1",
    )
    # Cannot succeed while still PENDING
    with pytest.raises(ValueError):
        run.succeed()


def test_sync_run_record_page() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INCREMENTAL,
        generation_id=1,
        trace_id="trc_1",
    )
    run.start()
    run.record_page(records_in_page=100, bytes_size=10240, next_checkpoint="c1")
    run.record_page(records_in_page=50, bytes_size=5120, next_checkpoint="c2")

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
    run.start()
    run.record_page(records_in_page=200, bytes_size=20480, next_checkpoint="cursor_final")
    run.succeed(end_checkpoint="cursor_final")

    assert run.status == SyncRunStatus.SUCCEEDED
    assert run.finished_at is not None
    assert run.end_checkpoint == "cursor_final"

    event_types = [type(e) for e in run.domain_events]
    assert SyncRunStartedEvent in event_types
    assert SyncRunCompletedEvent in event_types
    assert GenerationCompletedEvent in event_types


def test_sync_run_fail_emits_event() -> None:
    run = SyncRun.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="invoices",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
        trace_id="trc_1",
    )
    run.start()
    run.fail(error_code="RATE_LIMIT_EXCEEDED", error_message="HTTP 429 Too Many Requests")

    assert run.status == SyncRunStatus.FAILED
    assert run.error_code == "RATE_LIMIT_EXCEEDED"
    assert run.error_message == "HTTP 429 Too Many Requests"

    failed_events = [e for e in run.domain_events if isinstance(e, SyncRunFailedEvent)]
    assert len(failed_events) == 1
    assert failed_events[0].error_code == "RATE_LIMIT_EXCEEDED"
