"""SQLAlchemy repository adapter for GlobalEntityMap (GEM) aggregates."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import GlobalEntityMapModel
from ip.engine.domain.enums import NormalizedEntityType
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyGlobalEntityMapRepository(TenantSqlAlchemyRepository, GlobalEntityMapRepositoryPort):
    """Repository persisting and querying GlobalEntityMap crosswalk aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: GlobalEntityMapModel) -> GlobalEntityMap:
        return GlobalEntityMap(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            entity_domain=NormalizedEntityType(orm.entity_domain),
            canonical_id=orm.canonical_id,
            source_connection_id=orm.source_connection_id,
            source_entity_id=orm.source_entity_id,
            dest_connection_id=orm.dest_connection_id,
            dest_entity_id=orm.dest_entity_id,
            created_at=orm.created_at,
        )

    @staticmethod
    def _update_record_from_domain(orm: GlobalEntityMapModel, domain: GlobalEntityMap) -> None:
        orm.canonical_id = domain.canonical_id
        orm.dest_connection_id = domain.dest_connection_id
        orm.dest_entity_id = domain.dest_entity_id
        orm.trace_id = domain.trace_id
        orm.correlation_id = domain.correlation_id
        orm.parent_trace_id = domain.parent_trace_id
        orm.original_trace_id = domain.original_trace_id
        orm.replay_count = domain.replay_count

    async def save(self, entity_map: GlobalEntityMap) -> None:
        stmt = select(GlobalEntityMapModel).where(GlobalEntityMapModel.id == entity_map.id)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            orm = GlobalEntityMapModel(
                id=entity_map.id,
                tenant_id=entity_map.tenant_id,
                trace_id=entity_map.trace_id,
                correlation_id=entity_map.correlation_id,
                parent_trace_id=entity_map.parent_trace_id,
                original_trace_id=entity_map.original_trace_id,
                replay_count=entity_map.replay_count,
                entity_domain=entity_map.entity_domain.value,
                canonical_id=entity_map.canonical_id,
                source_connection_id=entity_map.source_connection_id,
                source_entity_id=entity_map.source_entity_id,
                dest_connection_id=entity_map.dest_connection_id,
                dest_entity_id=entity_map.dest_entity_id,
                created_at=entity_map.created_at,
            )
            self._session.add(orm)
        else:
            self._update_record_from_domain(existing, entity_map)

        self._drain_trace_events(entity_map)
        self._drain_events(entity_map, default_tenant_id=entity_map.tenant_id)
        await self._session.flush()

    async def get_by_source(
        self,
        tenant_id: str,
        entity_domain: NormalizedEntityType,
        source_connection_id: str,
        source_entity_id: str,
    ) -> GlobalEntityMap | None:
        stmt = select(GlobalEntityMapModel).where(
            GlobalEntityMapModel.tenant_id == tenant_id,
            GlobalEntityMapModel.entity_domain == entity_domain.value,
            GlobalEntityMapModel.source_connection_id == source_connection_id,
            GlobalEntityMapModel.source_entity_id == source_entity_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_canonical_id(
        self,
        tenant_id: str,
        canonical_id: str,
    ) -> GlobalEntityMap | None:
        stmt = select(GlobalEntityMapModel).where(
            GlobalEntityMapModel.tenant_id == tenant_id,
            GlobalEntityMapModel.canonical_id == canonical_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)
