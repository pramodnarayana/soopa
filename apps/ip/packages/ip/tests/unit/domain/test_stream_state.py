"""Unit tests for ConnectionStreamState aggregate root."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.domain.events import StreamStateCheckpointedEvent
from ip.domain.models.stream_state import ConnectionStreamState


def test_create_connection_stream_state() -> None:
    state = ConnectionStreamState.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream_name="contacts",
        cursor_field="updated_at",
        initial_cursor="2026-01-01T00:00:00Z",
    )
    assert state.id.startswith("ip_cst_")
    assert state.tenant_id == "tenant_123"
    assert state.connection_id == "conn_456"
    assert state.stream_name == "contacts"
    assert state.cursor_field == "updated_at"
    assert state.cursor_value == "2026-01-01T00:00:00Z"
    assert state.records_synced_count == 0
    assert len(state.domain_events) == 0


def test_advance_checkpoint_updates_cursor_and_emits_event() -> None:
    state = ConnectionStreamState.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream_name="contacts",
        cursor_field="updated_at",
    )
    assert state.cursor_value is None

    checkpoint_time = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    state.advance_checkpoint(
        new_cursor_value="2026-10-20T12:00:00Z",
        records_in_batch=50,
        synced_at=checkpoint_time,
    )

    assert state.cursor_value == "2026-10-20T12:00:00Z"
    assert state.records_synced_count == 50
    assert state.last_synced_at == checkpoint_time

    events = state.domain_events
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, StreamStateCheckpointedEvent)
    assert event.state_id == state.id
    assert event.tenant_id == "tenant_123"
    assert event.connection_id == "conn_456"
    assert event.stream_name == "contacts"
    assert event.cursor_value == "2026-10-20T12:00:00Z"
    assert event.records_synced_count == 50


def test_advance_checkpoint_accumulates_counts() -> None:
    state = ConnectionStreamState.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream_name="invoices",
        cursor_field="id",
    )
    state.advance_checkpoint(new_cursor_value="inv_001", records_in_batch=10)
    state.advance_checkpoint(new_cursor_value="inv_025", records_in_batch=15)

    assert state.cursor_value == "inv_025"
    assert state.records_synced_count == 25


def test_reset_checkpoint_resets_cursor_and_count() -> None:
    state = ConnectionStreamState.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream_name="contacts",
        cursor_field="updated_at",
        initial_cursor="2026-01-01T00:00:00Z",
    )
    state.advance_checkpoint(new_cursor_value="2026-05-01T00:00:00Z", records_in_batch=100)
    assert state.cursor_value == "2026-05-01T00:00:00Z"
    assert state.records_synced_count == 100

    state.reset_checkpoint()
    assert state.cursor_value is None
    assert state.records_synced_count == 0
