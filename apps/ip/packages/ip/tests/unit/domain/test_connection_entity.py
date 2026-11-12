"""Pure zero-mock unit tests for ConnectionEntity aggregate root."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from identity.domain.constants import IdentityIdPrefix
from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import EntitySyncFrom, EntitySyncSchedule, SyncMode
from ip.engine.domain.replication.events import ConnectionEntityCheckpointedEvent
from seedwork.utils import generate_id


def test_create_connection_entity_initializes_unsynced_state() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    entity = ConnectionEntity.create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="contacts",
        sync_mode=SyncMode.INCREMENTAL,
        schedule=EntitySyncSchedule.HOURLY,
        primary_key=["id"],
        fields=[StreamField(name="id", data_type="string", nullable=False)],
        cursor_field="updated_at",
    )
    assert entity.id.startswith("ip_cent_")
    assert entity.tenant_id == tenant_id
    assert entity.connection_id == connection_id
    assert entity.stream_name == "contacts"
    assert entity.sync_mode == SyncMode.INCREMENTAL
    assert entity.schedule == EntitySyncSchedule.HOURLY
    assert entity.sync_from == EntitySyncFrom.ALL
    assert entity.sync_from_at is None
    assert entity.primary_key == ("id",)
    assert len(entity.fields) == 1
    assert entity.cursor_field == "updated_at"
    assert entity.cursor_value is None
    assert entity.records_synced_count == 0
    assert entity.last_synced_at is None
    assert len(entity.domain_events) == 0


def test_try_create_rejects_invalid_identifiers_or_missing_custom_date() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)

    empty_tenant = ConnectionEntity.try_create(
        tenant_id="  ",
        connection_id=connection_id,
        stream_name="orders",
    )
    assert empty_tenant.is_err

    empty_connection = ConnectionEntity.try_create(
        tenant_id=tenant_id,
        connection_id="  ",
        stream_name="orders",
    )
    assert empty_connection.is_err

    empty_stream = ConnectionEntity.try_create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="  ",
    )
    assert empty_stream.is_err

    missing_custom_date = ConnectionEntity.try_create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="orders",
        sync_from=EntitySyncFrom.CUSTOM,
        sync_from_at=None,
    )
    assert missing_custom_date.is_err

    with pytest.raises(ValueError, match="sync_from_at is required"):
        ConnectionEntity.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name="orders",
            sync_from=EntitySyncFrom.CUSTOM,
        )


def test_update_configuration_mutates_schedule_policy_preserving_watermark() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    entity = ConnectionEntity.create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="orders",
        cursor_field="updated_at",
    )
    entity.advance_checkpoint(new_cursor_value="2026-10-20T00:00:00Z", records_in_batch=42)

    invalid_res = entity.update_configuration(sync_from=EntitySyncFrom.CUSTOM, sync_from_at=None)
    assert invalid_res.is_err

    custom_dt = datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC)
    valid_res = entity.update_configuration(
        schedule=EntitySyncSchedule.EVERY_15M,
        sync_from=EntitySyncFrom.CUSTOM,
        sync_from_at=custom_dt,
        is_enabled=False,
    )
    assert valid_res.is_ok
    assert entity.schedule == EntitySyncSchedule.EVERY_15M
    assert entity.sync_from == EntitySyncFrom.CUSTOM
    assert entity.sync_from_at == custom_dt
    assert entity.is_enabled is False
    assert entity.cursor_value == "2026-10-20T00:00:00Z"
    assert entity.records_synced_count == 42

    reset_to_all = entity.update_configuration(sync_from=EntitySyncFrom.ALL)
    assert reset_to_all.is_ok
    assert entity.sync_from == EntitySyncFrom.ALL
    assert entity.sync_from_at is None


def test_refresh_schema_updates_metadata_preserving_watermark() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    entity = ConnectionEntity.create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="invoices",
    )
    entity.advance_checkpoint(new_cursor_value="inv_10", records_in_batch=10)
    entity.refresh_schema(
        primary_key=["invoice_id"],
        fields=[StreamField(name="invoice_id", data_type="string", nullable=False)],
        cursor_field="modified_at",
        sync_mode=SyncMode.FULL_REFRESH,
    )
    assert entity.primary_key == ("invoice_id",)
    assert entity.fields[0].name == "invoice_id"
    assert entity.cursor_field == "modified_at"
    assert entity.sync_mode == SyncMode.FULL_REFRESH
    assert entity.records_synced_count == 10


def test_advance_checkpoint_updates_cursor_emitting_checkpoint_event() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    entity = ConnectionEntity.create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="contacts",
        cursor_field="updated_at",
    )
    checkpoint_time = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    entity.advance_checkpoint(
        new_cursor_value="2026-10-20T12:00:00Z",
        records_in_batch=50,
        synced_at=checkpoint_time,
    )
    assert entity.cursor_value == "2026-10-20T12:00:00Z"
    assert entity.records_synced_count == 50
    assert entity.last_synced_at == checkpoint_time

    events = entity.domain_events
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ConnectionEntityCheckpointedEvent)
    assert event.entity_id == entity.id
    assert event.tenant_id == tenant_id
    assert event.connection_id == connection_id
    assert event.stream_name == "contacts"
    assert event.cursor_value == "2026-10-20T12:00:00Z"
    assert event.records_synced_count == 50


def test_reset_checkpoint_clears_watermark_preserving_subscription() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    entity = ConnectionEntity.create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="contacts",
        schedule=EntitySyncSchedule.DAILY,
        cursor_field="updated_at",
        initial_cursor="2026-01-01T00:00:00Z",
    )
    entity.advance_checkpoint(new_cursor_value="2026-05-01T00:00:00Z", records_in_batch=100)
    entity.reset_checkpoint()

    assert entity.cursor_value is None
    assert entity.records_synced_count == 0
    assert entity.last_synced_at is None
    assert entity.schedule == EntitySyncSchedule.DAILY
