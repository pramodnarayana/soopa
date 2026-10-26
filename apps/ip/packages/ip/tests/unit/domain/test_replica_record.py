"""Unit tests for ReplicaRecord domain aggregate and canonical SHA-256 hash computation."""

from __future__ import annotations

from ip.engine.domain.enums import CursorKind, IpTraceEventType, MergeOutcome
from ip.engine.domain.events import ReplicaRecordChangedEvent
from ip.engine.domain.models.replica_record import (
    ReplicaRecord,
    ReplicaRejection,
    _is_cursor_stale,
    compute_data_hash,
)
from strace.domain import TracedAggregateRoot


def test_compute_data_hash_is_canonical_and_key_order_independent() -> None:
    hash_1 = compute_data_hash({"b": 2, "a": 1, "nested": {"y": True, "x": False}})
    hash_2 = compute_data_hash({"a": 1, "nested": {"x": False, "y": True}, "b": 2})

    assert hash_1 == hash_2
    assert len(hash_1) == 64


def test_replica_record_create_and_idempotent_update_snapshot() -> None:
    replica = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="ip_conn_01",
        stream="meter",
        record_key="MTR-100",
        primary_key_values=("MTR-100",),
        data={"serial": "MTR-100", "kwh": 12.5},
        source_inbound_record_id="inb_01",
        trace_id="ip_trc_01",
        correlation_id="corr-01",
    )

    assert isinstance(replica, TracedAggregateRoot)
    assert replica.id.startswith("ip_rep_")
    assert replica.version == 1
    assert len(replica.trace_events) == 1
    assert replica.trace_events[0].event_type == IpTraceEventType.L2_REPLICA_CREATED.value
    assert len(replica.domain_events) == 1
    assert isinstance(replica.domain_events[0], ReplicaRecordChangedEvent)
    assert replica.domain_events[0].outcome == MergeOutcome.INSERT.value

    replica.clear_trace_events()
    replica.clear_domain_events()

    # 1. Updating with identical data (different key order) is a no-op
    mutated = replica.update_snapshot(
        new_data={"kwh": 12.5, "serial": "MTR-100"},
        trace_id="ip_trc_02",
    )
    assert mutated is False
    assert replica.version == 1
    assert len(replica.trace_events) == 0
    assert len(replica.domain_events) == 0

    # 2. Updating with modified payload increments version and emits trace + domain event
    mutated_2 = replica.update_snapshot(
        new_data={"serial": "MTR-100", "kwh": 19.75},
        trace_id="ip_trc_03",
        correlation_id="corr-03",
        parent_trace_id="ip_trc_01",
        original_trace_id="ip_trc_01",
        replay_count=1,
        source_inbound_record_id="inb_02",
    )
    assert mutated_2 is True
    assert replica.version == 2
    assert replica.source_inbound_record_id == "inb_02"
    assert replica.trace_id == "ip_trc_03"
    assert replica.parent_trace_id == "ip_trc_01"
    assert replica.replay_count == 1
    assert len(replica.trace_events) == 1
    assert replica.trace_events[0].event_type == IpTraceEventType.L2_REPLICA_UPDATED.value
    assert len(replica.domain_events) == 1
    event = replica.domain_events[0]
    assert isinstance(event, ReplicaRecordChangedEvent)
    assert event.outcome == MergeOutcome.UPDATE.value
    assert event.data_hash == replica.data_hash


def test_replica_record_create_tombstone_and_rejection_create() -> None:
    tomb = ReplicaRecord.create_tombstone(
        tenant_id="ten_01",
        connection_id="ip_conn_01",
        stream="meter",
        record_key="MTR-DEL-01",
        primary_key_values=("MTR-DEL-01",),
        data={"serial": "MTR-DEL-01", "deleted": True},
        trace_id="ip_trc_del",
    )
    assert tomb.deleted_at is not None
    assert tomb.version == 1
    assert len(tomb.domain_events) == 1
    event = tomb.domain_events[0]
    assert isinstance(event, ReplicaRecordChangedEvent)
    assert event.outcome == MergeOutcome.TOMBSTONE.value

    rej = ReplicaRejection.create(
        tenant_id="ten_01",
        connection_id="ip_conn_01",
        stream="meter",
        inbound_record_id="inb_01",
        record_index=0,
        reason="MISSING_PRIMARY_KEY",
        detail="Missing serial",
        trace_id="ip_trc_del",
    )
    assert rej.id.startswith("ip_rej_")


def test_is_cursor_stale_datetime() -> None:
    # 2026-10-23T10:00:00Z vs 2026-10-23T11:00:00Z (incoming is older than existing -> stale)
    assert (
        _is_cursor_stale(
            existing_cursor="2026-10-23T11:00:00Z",
            incoming_cursor="2026-10-23T10:00:00Z",
            cursor_kind=CursorKind.DATETIME,
        )
        is True
    )

    # Incoming is newer -> not stale
    assert (
        _is_cursor_stale(
            existing_cursor="2026-10-23T10:00:00Z",
            incoming_cursor="2026-10-23T11:00:00+00:00",
            cursor_kind=CursorKind.DATETIME,
        )
        is False
    )


def test_replica_record_tombstone_revival_with_same_payload() -> None:
    replica = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="ip_conn_01",
        stream="meter",
        record_key="MTR-200",
        data={"serial": "MTR-200", "kwh": 50},
        trace_id="trc_01",
    )
    replica.tombstone(trace_id="trc_del")
    assert replica.deleted_at is not None

    # Reviving with identical payload must NOT be skipped as noop
    mutated = replica.update_snapshot(
        new_data={"serial": "MTR-200", "kwh": 50},
        trace_id="trc_revive",
    )
    assert mutated is True
    assert replica.deleted_at is None
    assert replica.version == 3
