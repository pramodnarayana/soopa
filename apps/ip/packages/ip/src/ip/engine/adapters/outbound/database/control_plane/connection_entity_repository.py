"""SQLAlchemy implementation of ConnectionEntityRepositoryPort."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionEntityRecord
from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import EntitySyncFrom, EntitySyncSchedule, SyncMode
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from seedwork.domain.types import JsonDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyConnectionEntityRepository(
    GlobalSqlAlchemyRepository, ConnectionEntityRepositoryPort
):
    """SQLAlchemy repository adapter for persisting and retrieving ConnectionEntity aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _serialize_fields(fields: Sequence[StreamField]) -> list[JsonDict]:
        return [
            {
                "name": f.name,
                "data_type": f.data_type,
                "nullable": f.nullable,
                "description": f.description,
            }
            for f in fields
        ]

    @staticmethod
    def _deserialize_fields(raw_fields: Sequence[JsonDict]) -> tuple[StreamField, ...]:
        parsed: list[StreamField] = []
        for item in raw_fields:
            name_val = item.get("name")
            if not isinstance(name_val, str) or not name_val:
                continue
            data_type_val = item.get("data_type")
            nullable_val = item.get("nullable")
            desc_val = item.get("description")
            parsed.append(
                StreamField(
                    name=name_val,
                    data_type=data_type_val if isinstance(data_type_val, str) else "string",
                    nullable=nullable_val if isinstance(nullable_val, bool) else True,
                    description=desc_val if isinstance(desc_val, str) else None,
                )
            )
        return tuple(parsed)

    @classmethod
    def _to_domain_model(cls, record: ConnectionEntityRecord) -> ConnectionEntity:
        """Strict explicit data mapper from ORM record to Domain Aggregate Root."""
        return ConnectionEntity(
            id=record.id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream_name=record.stream_name,
            sync_mode=SyncMode(record.sync_mode),
            schedule=EntitySyncSchedule(record.schedule),
            sync_from=EntitySyncFrom(record.sync_from),
            sync_from_at=record.sync_from_at,
            is_enabled=record.is_enabled,
            primary_key=tuple(pk for pk in record.primary_key if isinstance(pk, str)),
            fields=cls._deserialize_fields(record.fields_schema),
            cursor_field=record.cursor_field,
            cursor_value=record.cursor_value,
            records_synced_count=record.records_synced_count,
            last_synced_at=record.last_synced_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @classmethod
    def _to_orm_model(cls, entity: ConnectionEntity) -> ConnectionEntityRecord:
        return ConnectionEntityRecord(
            id=entity.id,
            tenant_id=entity.tenant_id,
            connection_id=entity.connection_id,
            stream_name=entity.stream_name,
            sync_mode=entity.sync_mode.value,
            schedule=entity.schedule.value,
            sync_from=entity.sync_from.value,
            sync_from_at=entity.sync_from_at,
            is_enabled=entity.is_enabled,
            primary_key=list(entity.primary_key),
            fields_schema=cls._serialize_fields(entity.fields),
            cursor_field=entity.cursor_field,
            cursor_value=entity.cursor_value,
            records_synced_count=entity.records_synced_count,
            last_synced_at=entity.last_synced_at,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @classmethod
    def _update_record_from_domain(
        cls,
        record: ConnectionEntityRecord,
        entity: ConnectionEntity,
    ) -> None:
        """Strict explicit data mapper updating ORM record fields from Domain Aggregate."""
        record.sync_mode = entity.sync_mode.value
        record.schedule = entity.schedule.value
        record.sync_from = entity.sync_from.value
        record.sync_from_at = entity.sync_from_at
        record.is_enabled = entity.is_enabled
        record.primary_key = list(entity.primary_key)
        record.fields_schema = cls._serialize_fields(entity.fields)
        record.cursor_field = entity.cursor_field
        record.cursor_value = entity.cursor_value
        record.records_synced_count = entity.records_synced_count
        record.last_synced_at = entity.last_synced_at
        record.updated_at = entity.updated_at

    async def get_by_stream(
        self,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
    ) -> ConnectionEntity | None:
        stmt = (
            select(ConnectionEntityRecord)
            .where(
                ConnectionEntityRecord.tenant_id == tenant_id,
                ConnectionEntityRecord.connection_id == connection_id,
                ConnectionEntityRecord.stream_name == stream_name,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
    ) -> Sequence[ConnectionEntity]:
        stmt = (
            select(ConnectionEntityRecord)
            .where(
                ConnectionEntityRecord.tenant_id == tenant_id,
                ConnectionEntityRecord.connection_id == connection_id,
            )
            .order_by(ConnectionEntityRecord.stream_name.asc())
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def save(self, entity: ConnectionEntity) -> None:
        stmt = (
            select(ConnectionEntityRecord)
            .where(
                ConnectionEntityRecord.tenant_id == entity.tenant_id,
                ConnectionEntityRecord.connection_id == entity.connection_id,
                ConnectionEntityRecord.stream_name == entity.stream_name,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            self._update_record_from_domain(existing, entity)
        else:
            self._session.add(self._to_orm_model(entity))

        self._drain_events(entity, default_tenant_id=entity.tenant_id)
        await self._session.flush()

    async def delete(self, entity: ConnectionEntity) -> None:
        self._drain_events(entity, default_tenant_id=entity.tenant_id)
        await self._session.execute(
            delete(ConnectionEntityRecord).where(
                ConnectionEntityRecord.tenant_id == entity.tenant_id,
                ConnectionEntityRecord.connection_id == entity.connection_id,
                ConnectionEntityRecord.stream_name == entity.stream_name,
            )
        )
        await self._session.flush()


__all__ = ["SqlAlchemyConnectionEntityRepository"]
