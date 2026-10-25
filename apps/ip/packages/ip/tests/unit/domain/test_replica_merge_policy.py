"""Unit tests for ReplicaMergePolicy (pure domain service)."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.domain.enums import CursorKind, MergeOutcome
from ip.engine.domain.models.replica_record import ReplicaMergePolicy, ReplicaRecord


def _make_existing(
    *,
    data_hash: str = "hash_v1",
    cursor_value: str | None = None,
    cursor_kind: str | None = None,
    deleted: bool = False,
) -> ReplicaRecord:
    record = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        record_key="MTR-01",
        data={"val": 1},
        trace_id="trc_01",
    )
    record.data_hash = data_hash
    record.cursor_value = cursor_value
    record.cursor_kind = cursor_kind
    if deleted:
        record.deleted_at = datetime.now(UTC)
    return record


def test_merge_policy_insert_when_no_existing_record() -> None:
    outcome = ReplicaMergePolicy.evaluate(
        existing=None,
        incoming_data_hash="new_hash",
        incoming_cursor="100",
        cursor_kind=CursorKind.INTEGER,
        is_deleted=False,
    )
    assert outcome == MergeOutcome.INSERT


def test_merge_policy_tombstone_when_is_deleted_true() -> None:
    existing = _make_existing()
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="any_hash",
        is_deleted=True,
    )
    assert outcome == MergeOutcome.TOMBSTONE


def test_merge_policy_noop_when_already_tombstoned_and_is_deleted_true() -> None:
    existing = _make_existing(deleted=True)
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="any_hash",
        is_deleted=True,
    )
    assert outcome == MergeOutcome.NOOP


def test_merge_policy_noop_when_hashes_match() -> None:
    existing = _make_existing(data_hash="same_hash", cursor_value="10")
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="same_hash",
        incoming_cursor="11",
        cursor_kind=CursorKind.INTEGER,
    )
    assert outcome == MergeOutcome.NOOP


def test_merge_policy_update_when_hashes_differ_and_cursor_advances() -> None:
    existing = _make_existing(data_hash="old_hash", cursor_value="10")
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="new_hash",
        incoming_cursor="11",
        cursor_kind=CursorKind.INTEGER,
    )
    assert outcome == MergeOutcome.UPDATE


def test_merge_policy_stale_when_integer_cursor_is_older() -> None:
    existing = _make_existing(data_hash="old_hash", cursor_value="100")
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="new_hash",
        incoming_cursor=99,
        cursor_kind=CursorKind.INTEGER,
    )
    assert outcome == MergeOutcome.STALE


def test_merge_policy_stale_when_datetime_cursor_is_older() -> None:
    existing = _make_existing(data_hash="old_hash", cursor_value="2026-10-22T10:00:00Z")
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="new_hash",
        incoming_cursor="2026-10-22T09:00:00Z",
        cursor_kind=CursorKind.DATETIME,
    )
    assert outcome == MergeOutcome.STALE


def test_merge_policy_resurrects_previously_deleted_record() -> None:
    existing = _make_existing(data_hash="old_hash", deleted=True)
    outcome = ReplicaMergePolicy.evaluate(
        existing=existing,
        incoming_data_hash="new_hash",
        is_deleted=False,
    )
    assert outcome == MergeOutcome.UPDATE
