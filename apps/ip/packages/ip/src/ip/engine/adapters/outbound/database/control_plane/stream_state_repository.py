"""SQLAlchemy implementation of StreamStateRepositoryPort."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import (
    ConnectionStreamStateRecord,
)
from ip.engine.domain.models.stream_state import ConnectionStreamState
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyStreamStateRepository(GlobalSqlAlchemyRepository, StreamStateRepositoryPort):
    """SQLAlchemy repository adapter for persisting and retrieving ConnectionStreamState aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: ConnectionStreamStateRecord) -> ConnectionStreamState:
        """Strict explicit data mapper from ORM record to Domain Aggregate Root."""
        return ConnectionStreamState(
            id=record.id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream_name=record.stream_name,
            cursor_field=record.cursor_field,
            cursor_value=record.cursor_value,
            records_synced_count=record.records_synced_count,
            last_synced_at=record.last_synced_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: ConnectionStreamStateRecord,
        state: ConnectionStreamState,
    ) -> None:
        """Strict explicit data mapper updating ORM record fields from Domain Aggregate."""
        record.cursor_field = state.cursor_field
        record.cursor_value = state.cursor_value
        record.records_synced_count = state.records_synced_count
        record.last_synced_at = state.last_synced_at

    async def get_by_stream(
        self,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
    ) -> ConnectionStreamState | None:
        stmt = (
            select(ConnectionStreamStateRecord)
            .where(
                ConnectionStreamStateRecord.tenant_id == tenant_id,
                ConnectionStreamStateRecord.connection_id == connection_id,
                ConnectionStreamStateRecord.stream_name == stream_name,
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
    ) -> Sequence[ConnectionStreamState]:
        stmt = (
            select(ConnectionStreamStateRecord)
            .where(
                ConnectionStreamStateRecord.tenant_id == tenant_id,
                ConnectionStreamStateRecord.connection_id == connection_id,
            )
            .order_by(ConnectionStreamStateRecord.stream_name.asc())
        )
        result = await self._session.execute(stmt)
        records = result.scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def save(self, state: ConnectionStreamState) -> None:
        stmt = (
            select(ConnectionStreamStateRecord)
            .where(
                ConnectionStreamStateRecord.tenant_id == state.tenant_id,
                ConnectionStreamStateRecord.connection_id == state.connection_id,
                ConnectionStreamStateRecord.stream_name == state.stream_name,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            self._update_record_from_domain(existing, state)
        else:
            new_record = ConnectionStreamStateRecord(
                id=state.id,
                tenant_id=state.tenant_id,
                connection_id=state.connection_id,
                stream_name=state.stream_name,
                cursor_field=state.cursor_field,
                cursor_value=state.cursor_value,
                records_synced_count=state.records_synced_count,
                last_synced_at=state.last_synced_at,
            )
            self._session.add(new_record)

        self._drain_events(state, default_tenant_id=state.tenant_id)
        await self._session.flush()
