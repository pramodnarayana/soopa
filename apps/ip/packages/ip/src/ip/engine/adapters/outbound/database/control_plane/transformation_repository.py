"""SQLAlchemy repository adapter for Transformation aggregates in Control Plane."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import TransformationRecord
from ip.engine.domain.enums import TransformationMode
from ip.engine.domain.normalization import Transformation
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyTransformationRepository(GlobalSqlAlchemyRepository, TransformationRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of TransformationRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: TransformationRecord) -> Transformation:
        return Transformation(
            id=record.id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream=record.stream,
            transformation_id=record.transformation_id,
            transformation_version=record.transformation_version,
            mode=TransformationMode(record.mode),
            shadow_transformation_version=record.shadow_transformation_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _to_orm_model(transformation: Transformation) -> TransformationRecord:
        return TransformationRecord(
            id=transformation.id,
            tenant_id=transformation.tenant_id,
            connection_id=transformation.connection_id,
            stream=transformation.stream,
            transformation_id=transformation.transformation_id,
            transformation_version=transformation.transformation_version,
            shadow_transformation_version=transformation.shadow_transformation_version,
            mode=transformation.mode.value,
            created_at=transformation.created_at,
            updated_at=transformation.updated_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: TransformationRecord, transformation: Transformation
    ) -> None:
        record.transformation_id = transformation.transformation_id
        record.transformation_version = transformation.transformation_version
        record.shadow_transformation_version = transformation.shadow_transformation_version
        record.mode = transformation.mode.value
        record.updated_at = transformation.updated_at

    async def get_by_stream(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
    ) -> Transformation | None:
        """Retrieve active transformation for a tenant connection stream."""
        stmt = (
            select(TransformationRecord)
            .where(
                TransformationRecord.tenant_id == tenant_id,
                TransformationRecord.connection_id == connection_id,
                TransformationRecord.stream == stream,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def save(self, transformation: Transformation) -> None:
        """Upsert a transformation configuration."""
        stmt = select(TransformationRecord).where(TransformationRecord.id == transformation.id)
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(transformation))
        else:
            self._update_record_from_domain(record, transformation)

        self._drain_events(transformation, default_tenant_id=transformation.tenant_id)

    async def list_by_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> list[Transformation]:
        """List all configured stream transformations for a connection."""
        stmt = (
            select(TransformationRecord)
            .where(
                TransformationRecord.tenant_id == tenant_id,
                TransformationRecord.connection_id == connection_id,
            )
            .order_by(TransformationRecord.stream.asc())
        )
        result = await self.session.execute(stmt)
        return [self._to_domain_model(r) for r in result.scalars().all()]
