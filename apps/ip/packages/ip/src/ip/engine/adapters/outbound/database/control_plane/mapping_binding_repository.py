"""SQLAlchemy repository adapter for MappingBinding aggregates in Control Plane."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import MappingBindingRecord
from ip.engine.domain.enums import MappingMode
from ip.engine.domain.normalization import MappingBinding
from ip.engine.ports.outbound.mapping_binding_repository_port import (
    MappingBindingRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyMappingBindingRepository(GlobalSqlAlchemyRepository, MappingBindingRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of MappingBindingRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: MappingBindingRecord) -> MappingBinding:
        return MappingBinding(
            id=record.id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream=record.stream,
            mapping_id=record.mapping_id,
            mapping_version=record.mapping_version,
            mode=MappingMode(record.mode),
            shadow_mapping_version=record.shadow_mapping_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_orm_model(binding: MappingBinding) -> MappingBindingRecord:
        return MappingBindingRecord(
            id=binding.id,
            tenant_id=binding.tenant_id,
            connection_id=binding.connection_id,
            stream=binding.stream,
            mapping_id=binding.mapping_id,
            mapping_version=binding.mapping_version,
            shadow_mapping_version=binding.shadow_mapping_version,
            mode=binding.mode.value,
            created_at=binding.created_at,
            updated_at=binding.updated_at,
        )

    @staticmethod
    def _update_record_from_domain(record: MappingBindingRecord, binding: MappingBinding) -> None:
        record.mapping_id = binding.mapping_id
        record.mapping_version = binding.mapping_version
        record.shadow_mapping_version = binding.shadow_mapping_version
        record.mode = binding.mode.value
        record.updated_at = binding.updated_at

    async def get_by_stream(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
    ) -> MappingBinding | None:
        """Retrieve active mapping binding for a tenant connection stream."""
        stmt = (
            select(MappingBindingRecord)
            .where(
                MappingBindingRecord.tenant_id == tenant_id,
                MappingBindingRecord.connection_id == connection_id,
                MappingBindingRecord.stream == stream,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def save(self, binding: MappingBinding) -> None:
        """Upsert a mapping binding configuration."""
        stmt = select(MappingBindingRecord).where(MappingBindingRecord.id == binding.id)
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(binding))
        else:
            self._update_record_from_domain(record, binding)

        self._drain_events(binding, default_tenant_id=binding.tenant_id)

    async def list_by_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> list[MappingBinding]:
        """List all configured stream mapping bindings for a connection."""
        stmt = (
            select(MappingBindingRecord)
            .where(
                MappingBindingRecord.tenant_id == tenant_id,
                MappingBindingRecord.connection_id == connection_id,
            )
            .order_by(MappingBindingRecord.stream.asc())
        )
        result = await self.session.execute(stmt)
        return [self._to_domain_model(r) for r in result.scalars().all()]
