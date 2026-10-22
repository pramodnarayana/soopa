"""SQLAlchemy repository adapter for Layer 2 ReplicaRecord aggregates."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import ReplicaRecordModel
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyReplicaRecordRepository(TenantSqlAlchemyRepository, ReplicaRecordRepositoryPort):
    """Repository persisting and retrieving ReplicaRecord aggregates with transactional outbox draining."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: ReplicaRecordModel) -> ReplicaRecord:
        return ReplicaRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            connection_id=orm.connection_id,
            app_id=orm.app_id,
            entity_type=orm.entity_type,
            entity_id=orm.entity_id,
            data=dict(orm.data),
            data_hash=orm.data_hash,
            version=orm.version,
            synced_at=orm.synced_at,
        )

    @staticmethod
    def _update_record_from_domain(orm: ReplicaRecordModel, domain: ReplicaRecord) -> None:
        orm.data = dict(domain.data)
        orm.data_hash = domain.data_hash
        orm.trace_id = domain.trace_id
        orm.correlation_id = domain.correlation_id
        orm.parent_trace_id = domain.parent_trace_id
        orm.original_trace_id = domain.original_trace_id
        orm.replay_count = domain.replay_count
        orm.version = domain.version
        orm.synced_at = domain.synced_at

    async def get_by_entity(
        self,
        tenant_id: str,
        connection_id: str,
        entity_type: str,
        entity_id: str,
    ) -> ReplicaRecord | None:
        stmt = select(ReplicaRecordModel).where(
            ReplicaRecordModel.tenant_id == tenant_id,
            ReplicaRecordModel.connection_id == connection_id,
            ReplicaRecordModel.entity_type == entity_type,
            ReplicaRecordModel.entity_id == entity_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def save(self, record: ReplicaRecord) -> None:
        stmt = select(ReplicaRecordModel).where(ReplicaRecordModel.id == record.id)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            orm = ReplicaRecordModel(
                id=record.id,
                tenant_id=record.tenant_id,
                trace_id=record.trace_id,
                correlation_id=record.correlation_id,
                parent_trace_id=record.parent_trace_id,
                original_trace_id=record.original_trace_id,
                replay_count=record.replay_count,
                connection_id=record.connection_id,
                app_id=record.app_id,
                entity_type=record.entity_type,
                entity_id=record.entity_id,
                data=dict(record.data),
                data_hash=record.data_hash,
                version=record.version,
                synced_at=record.synced_at,
            )
            self._session.add(orm)
        else:
            self._update_record_from_domain(existing, record)

        self._drain_trace_events(record)
        self._drain_events(record, default_tenant_id=record.tenant_id)
        await self._session.flush()
