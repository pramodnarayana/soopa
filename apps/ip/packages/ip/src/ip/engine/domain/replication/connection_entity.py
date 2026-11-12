"""ConnectionEntity aggregate root representing a subscribed entity and its sync watermark on a connection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import InvalidConnectionConfigError, Result
from ip.engine.domain.replication.enums import EntitySyncFrom, EntitySyncSchedule, SyncMode
from ip.engine.domain.replication.events import ConnectionEntityCheckpointedEvent

__all__ = ["ConnectionEntity"]


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
        """Validates invariants and constructs a new ConnectionEntity aggregate."""
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

        return Result.ok(
            cls(
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
        )

    @classmethod
    def create(
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
    ) -> ConnectionEntity:
        """Creates a validated ConnectionEntity aggregate when inputs are already trusted."""
        res = cls.try_create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            sync_mode=sync_mode,
            schedule=schedule,
            sync_from=sync_from,
            sync_from_at=sync_from_at,
            is_enabled=is_enabled,
            primary_key=primary_key,
            fields=fields,
            cursor_field=cursor_field,
            initial_cursor=initial_cursor,
        )
        if res.is_err or res.value is None:
            err = res.error or InvalidConnectionConfigError(
                field_name="stream_name",
                message="Invalid connection entity configuration.",
            )
            raise ValueError(err.message)
        return res.value

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
