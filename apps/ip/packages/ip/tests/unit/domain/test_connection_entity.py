"""Pure zero-mock unit tests for ConnectionEntity aggregate root."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from identity.domain.constants import IdentityIdPrefix
from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import (
    EntitySyncFrom,
    EntitySyncSchedule,
    SyncMode,
    SyncRunKind,
)
from ip.engine.domain.replication.events import (
    ConnectionEntityCheckpointedEvent,
    ConnectionEntityCheckpointResetEvent,
    ConnectionEntityConfigurationUpdatedEvent,
    ConnectionEntitySubscribedEvent,
    ConnectionEntityUnsubscribedEvent,
)
from seedwork.utils import generate_id


def _create_entity(
    *,
    tenant_id: str | None = None,
    connection_id: str | None = None,
    stream_name: str = "contacts",
    sync_mode: SyncMode = SyncMode.INCREMENTAL,
    schedule: EntitySyncSchedule = EntitySyncSchedule.HOURLY,
    sync_from: EntitySyncFrom = EntitySyncFrom.ALL,
    sync_from_at: datetime | None = None,
    is_enabled: bool = True,
    primary_key: list[str] | None = None,
    fields: list[StreamField] | None = None,
    cursor_field: str | None = "updated_at",
    initial_cursor: str | None = None,
) -> ConnectionEntity:
    res = ConnectionEntity.try_create(
        tenant_id=tenant_id or generate_id(IdentityIdPrefix.TENANT.value),
        connection_id=connection_id or generate_id(IpIdPrefix.CONNECTION.value),
        stream_name=stream_name,
        sync_mode=sync_mode,
        schedule=schedule,
        sync_from=sync_from,
        sync_from_at=sync_from_at,
        is_enabled=is_enabled,
        primary_key=primary_key or ["id"],
        fields=fields or [StreamField(name="id", data_type="string", nullable=False)],
        cursor_field=cursor_field,
        initial_cursor=initial_cursor,
    )
    assert res.is_ok and res.value is not None
    return res.value


def test_try_create_connection_entity_emits_subscribed_event() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    entity = _create_entity(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="contacts",
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

    events = entity.domain_events
    assert len(events) == 1
    subscribed = events[0]
    assert isinstance(subscribed, ConnectionEntitySubscribedEvent)
    assert subscribed.entity_id == entity.id
    assert subscribed.tenant_id == tenant_id
    assert subscribed.connection_id == connection_id
    assert subscribed.stream_name == "contacts"


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
    assert missing_custom_date.error is not None
    assert missing_custom_date.error.code == IpErrorCode.INVALID_CONFIG


def test_update_configuration_emits_domain_event() -> None:
    entity = _create_entity(stream_name="orders")
    entity.clear_domain_events()
    entity.advance_checkpoint(new_cursor_value="2026-10-20T00:00:00Z", records_in_batch=42)
    entity.clear_domain_events()

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
    assert any(
        isinstance(ev, ConnectionEntityConfigurationUpdatedEvent) for ev in entity.domain_events
    )

    reset_to_all = entity.update_configuration(sync_from=EntitySyncFrom.ALL)
    assert reset_to_all.is_ok
    assert entity.sync_from == EntitySyncFrom.ALL
    assert entity.sync_from_at is None


def test_refresh_schema_updates_metadata_preserving_watermark() -> None:
    entity = _create_entity(stream_name="invoices")
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


def test_connection_entity_watermark_lifecycle_events() -> None:
    entity = _create_entity(
        stream_name="contacts",
        schedule=EntitySyncSchedule.DAILY,
        initial_cursor="2026-01-01T00:00:00Z",
    )
    entity.clear_domain_events()

    checkpoint_time = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    entity.advance_checkpoint(
        new_cursor_value="2026-10-20T12:00:00Z",
        records_in_batch=50,
        synced_at=checkpoint_time,
    )
    assert entity.cursor_value == "2026-10-20T12:00:00Z"
    assert entity.records_synced_count == 50
    assert entity.last_synced_at == checkpoint_time
    checkpointed = list(entity.domain_events)
    entity.clear_domain_events()
    assert len(checkpointed) == 1
    assert isinstance(checkpointed[0], ConnectionEntityCheckpointedEvent)

    entity.reset_checkpoint()
    assert entity.cursor_value is None
    assert entity.records_synced_count == 0
    assert entity.last_synced_at is None
    assert entity.schedule == EntitySyncSchedule.DAILY
    reset_events = list(entity.domain_events)
    entity.clear_domain_events()
    assert len(reset_events) == 1
    assert isinstance(reset_events[0], ConnectionEntityCheckpointResetEvent)

    entity.mark_unsubscribed()
    unsub_events = list(entity.domain_events)
    entity.clear_domain_events()
    assert len(unsub_events) == 1
    assert isinstance(unsub_events[0], ConnectionEntityUnsubscribedEvent)


def test_plan_sync_execution_resolves_initial_floor_cursor() -> None:
    now = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)

    all_entity = _create_entity(sync_from=EntitySyncFrom.ALL)
    assert all_entity.resolve_initial_floor_cursor(reference_time=now) is None

    for mode, days in (
        (EntitySyncFrom.LAST_24H, 1),
        (EntitySyncFrom.LAST_7D, 7),
        (EntitySyncFrom.LAST_30D, 30),
        (EntitySyncFrom.LAST_90D, 90),
    ):
        window_entity = _create_entity(sync_from=mode)
        assert (
            window_entity.resolve_initial_floor_cursor(reference_time=now)
            == (now - timedelta(days=days)).isoformat()
        )

    custom_dt = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    custom_entity = _create_entity(
        sync_from=EntitySyncFrom.CUSTOM,
        sync_from_at=custom_dt,
    )
    assert custom_entity.resolve_initial_floor_cursor(reference_time=now) == custom_dt.isoformat()

    plan_initial = custom_entity.plan_sync_execution(latest_generation_id=0, now=now)
    assert plan_initial.is_ok and plan_initial.value is not None
    assert plan_initial.value.kind == SyncRunKind.INITIAL
    assert plan_initial.value.start_checkpoint == custom_dt.isoformat()
    assert plan_initial.value.generation_id == 1

    plan_full = custom_entity.plan_sync_execution(
        latest_generation_id=1,
        forced_kind=SyncRunKind.FULL_REFRESH,
        now=now,
    )
    assert plan_full.is_ok and plan_full.value is not None
    assert plan_full.value.kind == SyncRunKind.FULL_REFRESH
    assert plan_full.value.start_checkpoint == custom_dt.isoformat()
    assert plan_full.value.generation_id == 2

    custom_entity.advance_checkpoint(new_cursor_value="2026-10-15T00:00:00Z", records_in_batch=5)
    plan_incremental = custom_entity.plan_sync_execution(latest_generation_id=1, now=now)
    assert plan_incremental.is_ok and plan_incremental.value is not None
    assert plan_incremental.value.kind == SyncRunKind.INCREMENTAL
    assert plan_incremental.value.start_checkpoint == "2026-10-15T00:00:00Z"

    disabled_entity = _create_entity(is_enabled=False)
    plan_disabled = disabled_entity.plan_sync_execution(latest_generation_id=0, now=now)
    assert plan_disabled.is_err
    assert plan_disabled.error is not None
    assert plan_disabled.error.code == IpErrorCode.CONNECTION_ENTITY_DISABLED
