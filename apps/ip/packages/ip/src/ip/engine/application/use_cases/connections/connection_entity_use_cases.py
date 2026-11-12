"""Control Plane use cases for managing subscribed ConnectionEntity aggregates and checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.exceptions import (
    ActiveSyncRunAlreadyExistsError,
    ConnectionEntityNotFoundError,
    ConnectionNotFoundError,
    IpError,
    Result,
)
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import EntitySyncFrom, EntitySyncSchedule, SyncMode
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ConnectionEntityFieldDTO:
    """Pure boundary DTO representing a field on a subscribed connection entity."""

    name: str
    data_type: str
    nullable: bool = True
    description: str | None = None


@dataclass(frozen=True)
class ConnectionEntitySummaryDTO:
    """Pure boundary DTO representing a subscribed ConnectionEntity aggregate."""

    entity_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    sync_mode: SyncMode
    schedule: EntitySyncSchedule
    sync_from: EntitySyncFrom
    sync_from_at: datetime | None
    is_enabled: bool
    primary_key: tuple[str, ...]
    fields: tuple[ConnectionEntityFieldDTO, ...]
    cursor_field: str | None
    cursor_value: str | None
    records_synced_count: int
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ListConnectionEntitiesQuery:
    """Query to list all subscribed entities for a connection."""

    tenant_id: str
    connection_id: str


@dataclass(frozen=True)
class AddConnectionEntityCommand:
    """Command to subscribe an entity stream on a connection."""

    tenant_id: str
    connection_id: str
    stream_name: str
    sync_mode: SyncMode = SyncMode.INCREMENTAL
    schedule: EntitySyncSchedule = EntitySyncSchedule.MANUAL
    sync_from: EntitySyncFrom = EntitySyncFrom.ALL
    sync_from_at: datetime | None = None
    is_enabled: bool = True
    primary_key: tuple[str, ...] = ()
    fields: tuple[ConnectionEntityFieldDTO, ...] = ()
    cursor_field: str | None = None


@dataclass(frozen=True)
class UpdateConnectionEntityCommand:
    """Command to update sync policy configuration on a subscribed connection entity."""

    tenant_id: str
    connection_id: str
    stream_name: str
    sync_mode: SyncMode | None = None
    schedule: EntitySyncSchedule | None = None
    sync_from: EntitySyncFrom | None = None
    sync_from_at: datetime | None = None
    is_enabled: bool | None = None


@dataclass(frozen=True)
class RemoveConnectionEntityCommand:
    """Command to unsubscribe and remove an entity from a connection."""

    tenant_id: str
    connection_id: str
    stream_name: str


@dataclass(frozen=True)
class ResetConnectionEntityCheckpointCommand:
    """Command to reset a subscribed entity's sync cursor and counters without unsubscribing."""

    tenant_id: str
    connection_id: str
    stream_name: str


def _to_entity_dto(entity: ConnectionEntity) -> ConnectionEntitySummaryDTO:
    return ConnectionEntitySummaryDTO(
        entity_id=entity.id,
        tenant_id=entity.tenant_id,
        connection_id=entity.connection_id,
        stream_name=entity.stream_name,
        sync_mode=entity.sync_mode,
        schedule=entity.schedule,
        sync_from=entity.sync_from,
        sync_from_at=entity.sync_from_at,
        is_enabled=entity.is_enabled,
        primary_key=entity.primary_key,
        fields=tuple(
            ConnectionEntityFieldDTO(
                name=f.name,
                data_type=f.data_type,
                nullable=f.nullable,
                description=f.description,
            )
            for f in entity.fields
        ),
        cursor_field=entity.cursor_field,
        cursor_value=entity.cursor_value,
        records_synced_count=entity.records_synced_count,
        last_synced_at=entity.last_synced_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class ListConnectionEntitiesUseCase:
    """Lists all subscribed entities configured on a connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: ListConnectionEntitiesQuery
    ) -> Result[tuple[ConnectionEntitySummaryDTO, ...], IpError]:
        bound = logger.bind(tenant_id=query.tenant_id, connection_id=query.connection_id)
        bound.info("list_connection_entities.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("list_connection_entities.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            entities = await self._cp_uow.entities.list_by_connection(
                tenant_id=query.tenant_id,
                connection_id=query.connection_id,
            )
            dtos = tuple(_to_entity_dto(e) for e in entities)
            bound.info("list_connection_entities.completed", count=len(dtos))
            return Result.ok(dtos)


class AddConnectionEntityUseCase:
    """Subscribes an entity stream on a connection (idempotent schema refresh if already subscribed)."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, command: AddConnectionEntityCommand
    ) -> Result[ConnectionEntitySummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("add_connection_entity.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("add_connection_entity.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            domain_fields = tuple(
                StreamField(
                    name=f.name,
                    data_type=f.data_type,
                    nullable=f.nullable,
                    description=f.description,
                )
                for f in command.fields
            )

            existing = await self._cp_uow.entities.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name.strip(),
            )
            if existing is not None:
                existing.refresh_schema(
                    primary_key=command.primary_key if command.primary_key else None,
                    fields=domain_fields if domain_fields else None,
                    cursor_field=command.cursor_field,
                    sync_mode=command.sync_mode,
                )
                entity = existing
            else:
                create_res = ConnectionEntity.try_create(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream_name=command.stream_name,
                    sync_mode=command.sync_mode,
                    schedule=command.schedule,
                    sync_from=command.sync_from,
                    sync_from_at=command.sync_from_at,
                    is_enabled=command.is_enabled,
                    primary_key=command.primary_key,
                    fields=domain_fields,
                    cursor_field=command.cursor_field,
                )
                if create_res.is_err or create_res.value is None:
                    err = create_res.unwrap_err()
                    bound.error("add_connection_entity.invalid_config", error_code=err.code.value)
                    return Result.err(err)
                entity = create_res.value

            await self._cp_uow.entities.save(entity)
            await self._cp_uow.commit()
            bound.info("add_connection_entity.completed", entity_id=entity.id)
            return Result.ok(_to_entity_dto(entity))


class UpdateConnectionEntityUseCase:
    """Updates sync configuration policy (schedule, sync_from, sync_mode, is_enabled) on a subscribed entity."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, command: UpdateConnectionEntityCommand
    ) -> Result[ConnectionEntitySummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("update_connection_entity.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("update_connection_entity.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            entity = await self._cp_uow.entities.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
            )
            if entity is None:
                bound.error("update_connection_entity.not_found")
                return Result.err(
                    ConnectionEntityNotFoundError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            upd_res = entity.update_configuration(
                sync_mode=command.sync_mode,
                schedule=command.schedule,
                sync_from=command.sync_from,
                sync_from_at=command.sync_from_at,
                is_enabled=command.is_enabled,
            )
            if upd_res.is_err:
                err = upd_res.unwrap_err()
                bound.error("update_connection_entity.invalid_config", error_code=err.code.value)
                return Result.err(err)

            await self._cp_uow.entities.save(entity)
            await self._cp_uow.commit()
            bound.info("update_connection_entity.completed", entity_id=entity.id)
            return Result.ok(_to_entity_dto(entity))


class RemoveConnectionEntityUseCase:
    """Removes a subscribed entity from a connection when no active sync run is in progress."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(self, command: RemoveConnectionEntityCommand) -> Result[None, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("remove_connection_entity.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("remove_connection_entity.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            active_run = await self._cp_uow.sync_runs.get_active_run(
                connection_id=command.connection_id,
                stream=command.stream_name,
                tenant_id=command.tenant_id,
            )
            if active_run is not None:
                bound.error(
                    "remove_connection_entity.active_run_exists",
                    existing_run_id=active_run.id,
                )
                return Result.err(
                    ActiveSyncRunAlreadyExistsError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            entity = await self._cp_uow.entities.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
            )
            if entity is None:
                bound.error("remove_connection_entity.not_found")
                return Result.err(
                    ConnectionEntityNotFoundError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            entity.mark_unsubscribed()
            await self._cp_uow.entities.delete(entity)
            await self._cp_uow.commit()
            bound.info("remove_connection_entity.completed", entity_id=entity.id)
            return Result.ok(None)


class ResetConnectionEntityCheckpointUseCase:
    """Resets a subscribed entity's checkpoint cursor to force full historical re-sync."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, command: ResetConnectionEntityCheckpointCommand
    ) -> Result[ConnectionEntitySummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("reset_connection_entity_checkpoint.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("reset_connection_entity_checkpoint.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            active_run = await self._cp_uow.sync_runs.get_active_run(
                connection_id=command.connection_id,
                stream=command.stream_name,
                tenant_id=command.tenant_id,
            )
            if active_run is not None:
                bound.error(
                    "reset_connection_entity_checkpoint.active_run_exists",
                    existing_run_id=active_run.id,
                )
                return Result.err(
                    ActiveSyncRunAlreadyExistsError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            entity = await self._cp_uow.entities.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
            )
            if entity is None:
                bound.error("reset_connection_entity_checkpoint.not_found")
                return Result.err(
                    ConnectionEntityNotFoundError.for_stream(
                        command.connection_id, command.stream_name
                    )
                )

            entity.reset_checkpoint()
            await self._cp_uow.entities.save(entity)
            await self._cp_uow.commit()
            bound.info("reset_connection_entity_checkpoint.completed", entity_id=entity.id)
            return Result.ok(_to_entity_dto(entity))


__all__ = [
    "AddConnectionEntityCommand",
    "AddConnectionEntityUseCase",
    "ConnectionEntityFieldDTO",
    "ConnectionEntitySummaryDTO",
    "ListConnectionEntitiesQuery",
    "ListConnectionEntitiesUseCase",
    "RemoveConnectionEntityCommand",
    "RemoveConnectionEntityUseCase",
    "ResetConnectionEntityCheckpointCommand",
    "ResetConnectionEntityCheckpointUseCase",
    "UpdateConnectionEntityCommand",
    "UpdateConnectionEntityUseCase",
]
