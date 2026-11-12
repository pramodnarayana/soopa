"""ConnectionEntity aggregate root representing a subscribed entity and its sync watermark on a connection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import (
    ConnectionEntityDisabledError,
    InvalidConnectionConfigError,
    IpError,
    Result,
)
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

__all__ = ["ConnectionEntity", "PlannedSyncExecution"]


@dataclass(frozen=True)
class PlannedSyncExecution:
    """Immutable domain value object describing the planned parameters for a stream sync run."""

    kind: SyncRunKind
    start_checkpoint: str | None
    generation_id: int


@dataclass(kw_only=True, eq=False)
class ConnectionEntity(AggregateRoot):
    """Aggregate Root representing a tenant-subscribed entity on a connection and its sync watermark."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.CONNECTION_ENTITY.value

    id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    sync_mode: SyncMode = SyncMode.INCREMENTAL
    schedule: EntitySyncSchedule = EntitySyncSchedule.MANUAL
    sync_from: EntitySyncFrom = EntitySyncFrom.ALL
    sync_from_at: datetime | None = None
    is_enabled: bool = True
    primary_key: tuple[str, ...] = ()
    fields: tuple[StreamField, ...] = ()
    cursor_field: str | None = None
    cursor_value: str | None = None
    records_synced_count: int = 0
    last_synced_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def try_create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        sync_mode: SyncMode = SyncMode.INCREMENTAL,
        schedule: EntitySyncSchedule = EntitySyncSchedule.MANUAL,
        sync_from: EntitySyncFrom = EntitySyncFrom.ALL,
        sync_from_at: datetime | None = None,
        is_enabled: bool = True,
        primary_key: Sequence[str] = (),
        fields: Sequence[StreamField] = (),
        cursor_field: str | None = None,
        initial_cursor: str | None = None,
    ) -> Result[ConnectionEntity, InvalidConnectionConfigError]:
        """Validates invariants, constructs a new ConnectionEntity aggregate, and records subscription event."""
        normalized_tenant_id = tenant_id.strip()
        if not normalized_tenant_id:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="tenant_id",
                    message="tenant_id cannot be empty.",
                )
            )
        normalized_connection_id = connection_id.strip()
        if not normalized_connection_id:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="connection_id",
                    message="connection_id cannot be empty.",
                )
            )
        normalized_stream = stream_name.strip()
        if not normalized_stream:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="stream_name",
                    message="stream_name cannot be empty.",
                )
            )
        if sync_from == EntitySyncFrom.CUSTOM and sync_from_at is None:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="sync_from_at",
                    message="sync_from_at is required when sync_from is 'custom'.",
                )
            )

        now = datetime.now(UTC)
        resolved_sync_from_at = sync_from_at if sync_from == EntitySyncFrom.CUSTOM else None
        normalized_cursor_field = (
            cursor_field.strip() if cursor_field and cursor_field.strip() else None
        )
        normalized_pk = tuple(pk.strip() for pk in primary_key if pk.strip())

        entity = cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=normalized_tenant_id,
            connection_id=normalized_connection_id,
            stream_name=normalized_stream,
            sync_mode=sync_mode,
            schedule=schedule,
            sync_from=sync_from,
            sync_from_at=resolved_sync_from_at,
            is_enabled=is_enabled,
            primary_key=normalized_pk,
            fields=tuple(fields),
            cursor_field=normalized_cursor_field,
            cursor_value=initial_cursor,
            records_synced_count=0,
            last_synced_at=None,
            created_at=now,
            updated_at=now,
        )
        entity.add_domain_event(
            ConnectionEntitySubscribedEvent(
                entity_id=entity.id,
                tenant_id=entity.tenant_id,
                connection_id=entity.connection_id,
                stream_name=entity.stream_name,
                sync_mode=entity.sync_mode.value,
                schedule=entity.schedule.value,
                sync_from=entity.sync_from.value,
                is_enabled=entity.is_enabled,
            )
        )
        return Result.ok(entity)

    def resolve_initial_floor_cursor(self, reference_time: datetime | None = None) -> str | None:
        """Computes the historical lookback floor cursor ISO-8601 timestamp from `sync_from` policy."""
        now = reference_time or datetime.now(UTC)
        utc_now = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)

        if self.sync_from == EntitySyncFrom.ALL:
            return None
        if self.sync_from == EntitySyncFrom.LAST_24H:
            return (utc_now - timedelta(hours=24)).isoformat()
        if self.sync_from == EntitySyncFrom.LAST_7D:
            return (utc_now - timedelta(days=7)).isoformat()
        if self.sync_from == EntitySyncFrom.LAST_30D:
            return (utc_now - timedelta(days=30)).isoformat()
        if self.sync_from == EntitySyncFrom.LAST_90D:
            return (utc_now - timedelta(days=90)).isoformat()
        if self.sync_from == EntitySyncFrom.CUSTOM and self.sync_from_at is not None:
            custom_ts = (
                self.sync_from_at.astimezone(UTC)
                if self.sync_from_at.tzinfo is not None
                else self.sync_from_at.replace(tzinfo=UTC)
            )
            return custom_ts.isoformat()
        return None

    def plan_sync_execution(
        self,
        *,
        latest_generation_id: int,
        forced_kind: SyncRunKind | None = None,
        now: datetime | None = None,
    ) -> Result[PlannedSyncExecution, IpError]:
        """Enforces subscription policy (`is_enabled`, `sync_mode`, `sync_from`, `cursor_value`) to plan a sync run."""
        if not self.is_enabled:
            return Result.fail(
                ConnectionEntityDisabledError.for_stream(self.connection_id, self.stream_name)
            )

        ref_now = now or datetime.now(UTC)
        floor_cursor = self.resolve_initial_floor_cursor(ref_now)

        if forced_kind == SyncRunKind.FULL_REFRESH or (
            forced_kind is None and self.sync_mode == SyncMode.FULL_REFRESH
        ):
            return Result.ok(
                PlannedSyncExecution(
                    kind=SyncRunKind.FULL_REFRESH,
                    start_checkpoint=floor_cursor,
                    generation_id=latest_generation_id + 1,
                )
            )

        base_generation = max(1, latest_generation_id)
        if forced_kind == SyncRunKind.RECONCILIATION:
            return Result.ok(
                PlannedSyncExecution(
                    kind=SyncRunKind.RECONCILIATION,
                    start_checkpoint=self.cursor_value if self.cursor_value else floor_cursor,
                    generation_id=base_generation,
                )
            )

        if forced_kind is not None:
            return Result.ok(
                PlannedSyncExecution(
                    kind=forced_kind,
                    start_checkpoint=self.cursor_value if self.cursor_value else floor_cursor,
                    generation_id=base_generation,
                )
            )

        if self.cursor_value:
            return Result.ok(
                PlannedSyncExecution(
                    kind=SyncRunKind.INCREMENTAL,
                    start_checkpoint=self.cursor_value,
                    generation_id=base_generation,
                )
            )

        return Result.ok(
            PlannedSyncExecution(
                kind=SyncRunKind.INITIAL,
                start_checkpoint=floor_cursor,
                generation_id=base_generation,
            )
        )

    def update_configuration(
        self,
        *,
        sync_mode: SyncMode | None = None,
        schedule: EntitySyncSchedule | None = None,
        sync_from: EntitySyncFrom | None = None,
        sync_from_at: datetime | None = None,
        is_enabled: bool | None = None,
    ) -> Result[None, InvalidConnectionConfigError]:
        """Updates subscription policy fields while preserving runtime watermark state."""
        next_sync_from = sync_from if sync_from is not None else self.sync_from
        next_sync_from_at = (
            sync_from_at
            if sync_from_at is not None
            else (self.sync_from_at if next_sync_from == EntitySyncFrom.CUSTOM else None)
        )
        if next_sync_from == EntitySyncFrom.CUSTOM and next_sync_from_at is None:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="sync_from_at",
                    message="sync_from_at is required when sync_from is 'custom'.",
                )
            )
        if next_sync_from != EntitySyncFrom.CUSTOM:
            next_sync_from_at = None

        if sync_mode is not None:
            self.sync_mode = sync_mode
        if schedule is not None:
            self.schedule = schedule
        self.sync_from = next_sync_from
        self.sync_from_at = next_sync_from_at
        if is_enabled is not None:
            self.is_enabled = is_enabled
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ConnectionEntityConfigurationUpdatedEvent(
                entity_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream_name=self.stream_name,
                sync_mode=self.sync_mode.value,
                schedule=self.schedule.value,
                sync_from=self.sync_from.value,
                is_enabled=self.is_enabled,
            )
        )
        return Result.ok(None)

    def refresh_schema(
        self,
        *,
        primary_key: Sequence[str] | None = None,
        fields: Sequence[StreamField] | None = None,
        cursor_field: str | None = None,
        sync_mode: SyncMode | None = None,
    ) -> None:
        """Refreshes cached field/key metadata from live connector discovery without resetting watermarks."""
        if primary_key is not None:
            self.primary_key = tuple(pk.strip() for pk in primary_key if pk.strip())
        if fields is not None:
            self.fields = tuple(fields)
        if cursor_field is not None:
            self.cursor_field = cursor_field.strip() if cursor_field.strip() else None
        if sync_mode is not None:
            self.sync_mode = sync_mode
        self.updated_at = datetime.now(UTC)

    def advance_checkpoint(
        self,
        new_cursor_value: str | None,
        records_in_batch: int = 1,
        synced_at: datetime | None = None,
    ) -> None:
        """Advances the entity sync watermark and increments synced record counters."""
        now = synced_at or datetime.now(UTC)
        self.records_synced_count += max(0, records_in_batch)
        self.last_synced_at = now
        self.updated_at = now

        if new_cursor_value:
            self.cursor_value = new_cursor_value
            self.add_domain_event(
                ConnectionEntityCheckpointedEvent(
                    entity_id=self.id,
                    tenant_id=self.tenant_id,
                    connection_id=self.connection_id,
                    stream_name=self.stream_name,
                    cursor_value=new_cursor_value,
                    records_synced_count=self.records_synced_count,
                )
            )

    def reset_checkpoint(self) -> None:
        """Resets sync cursor and counters to UNSYNCED while preserving entity subscription and schedule."""
        self.cursor_value = None
        self.records_synced_count = 0
        self.last_synced_at = None
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            ConnectionEntityCheckpointResetEvent(
                entity_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream_name=self.stream_name,
            )
        )

    def mark_unsubscribed(self) -> None:
        """Records the unsubscribed lifecycle domain event prior to aggregate deletion."""
        self.add_domain_event(
            ConnectionEntityUnsubscribedEvent(
                entity_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream_name=self.stream_name,
            )
        )
