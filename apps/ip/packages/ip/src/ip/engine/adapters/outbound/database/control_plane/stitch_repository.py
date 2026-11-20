"""SQLAlchemy repository adapter for Stitch aggregates in the Control Plane (`ip.stitches`)."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import StitchRecord
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from seedwork.domain.types import JsonDict, JsonPrimitive
from sqlalchemy import case, delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyStitchRepository(GlobalSqlAlchemyRepository, StitchRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of StitchRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _sanitize_filter_conditions(raw: object) -> dict[str, JsonPrimitive]:
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise TypeError(f"filter_conditions must be a dictionary, got {type(raw).__name__}")
        cleaned: dict[str, JsonPrimitive] = {}
        for k, v in raw.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                cleaned[str(k)] = v
            else:
                raise ValueError(
                    f"filter_conditions value for key '{k}' must be a primitive (str, int, float, bool, None), "
                    f"got {type(v).__name__}"
                )
        return cleaned

    @staticmethod
    def _to_domain_model(record: StitchRecord) -> Stitch:
        raw_filters = (
            dict(record.filter_conditions) if isinstance(record.filter_conditions, dict) else {}
        )
        idemp_field = str(raw_filters.pop("__idempotency_key_field__", "") or "")
        conc_field = str(raw_filters.pop("__concurrency_key_field__", "") or "")
        return Stitch(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            description=record.description,
            mapping_spec_id=record.mapping_spec_id,
            canonical_event_type=record.canonical_event_type,
            target_workflow_id=record.target_workflow_id,
            filter_conditions=SqlAlchemyStitchRepository._sanitize_filter_conditions(raw_filters),
            is_active=record.is_active,
            idempotency_key_field=idemp_field,
            concurrency_key_field=conc_field,
        )

    @staticmethod
    def _to_orm_model(stitch: Stitch, now: datetime) -> StitchRecord:
        raw_filters: JsonDict = dict(stitch.filter_conditions)
        if stitch.idempotency_key_field:
            raw_filters["__idempotency_key_field__"] = stitch.idempotency_key_field
        if stitch.concurrency_key_field:
            raw_filters["__concurrency_key_field__"] = stitch.concurrency_key_field
        return StitchRecord(
            id=stitch.id,
            tenant_id=stitch.tenant_id,
            name=stitch.name,
            description=stitch.description,
            mapping_spec_id=stitch.mapping_spec_id,
            canonical_event_type=stitch.canonical_event_type,
            target_workflow_id=stitch.target_workflow_id,
            filter_conditions=raw_filters,
            is_active=stitch.is_active,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _update_record_from_domain(
        record: StitchRecord,
        stitch: Stitch,
        now: datetime,
    ) -> None:
        raw_filters: JsonDict = dict(stitch.filter_conditions)
        if stitch.idempotency_key_field:
            raw_filters["__idempotency_key_field__"] = stitch.idempotency_key_field
        if stitch.concurrency_key_field:
            raw_filters["__concurrency_key_field__"] = stitch.concurrency_key_field
        record.tenant_id = stitch.tenant_id
        record.name = stitch.name
        record.description = stitch.description
        record.mapping_spec_id = stitch.mapping_spec_id
        record.canonical_event_type = stitch.canonical_event_type
        record.target_workflow_id = stitch.target_workflow_id
        record.filter_conditions = raw_filters
        record.is_active = stitch.is_active
        record.updated_at = now

    async def save(self, stitch: Stitch) -> None:
        """Upsert a Stitch configuration in ip.stitches."""
        now = datetime.now(UTC)
        stmt = select(StitchRecord).where(
            StitchRecord.id == stitch.id,
            StitchRecord.tenant_id == stitch.tenant_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(stitch, now))
        else:
            self._update_record_from_domain(record, stitch, now)

        self._drain_events(stitch, default_tenant_id=stitch.tenant_id)

    async def get_by_id(
        self,
        *,
        tenant_id: str,
        stitch_id: str,
    ) -> Stitch | None:
        """Retrieve a Stitch by ID for a tenant (prioritizing tenant-specific before wildcard '*')."""
        stmt = (
            select(StitchRecord)
            .where(
                StitchRecord.id == stitch_id,
                StitchRecord.tenant_id.in_((tenant_id, "*")),
            )
            .order_by(case((StitchRecord.tenant_id == tenant_id, 0), else_=1))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def get_by_id_global(
        self,
        *,
        stitch_id: str,
    ) -> Stitch | None:
        """Retrieve a Stitch by ID across all tenants for cross-tenant collision detection.

        Prioritizes concrete tenant records over wildcard '*' so collisions against
        concrete tenants are always detected.
        """
        stmt = (
            select(StitchRecord)
            .where(StitchRecord.id == stitch_id)
            .order_by(case((StitchRecord.tenant_id != "*", 0), else_=1))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
    ) -> list[Stitch]:
        """List all Stitches visible to a tenant (tenant-specific and wildcard '*')."""
        stmt = (
            select(StitchRecord)
            .where(StitchRecord.tenant_id.in_((tenant_id, "*")))
            .order_by(StitchRecord.id.asc())
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        by_id: dict[str, Stitch] = {}
        for r in records:
            if r.id not in by_id or r.tenant_id == tenant_id:
                by_id[r.id] = self._to_domain_model(r)
        return list(by_id.values())

    async def list_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> list[Stitch]:
        """List all active Stitches matching a tenant (or '*') and canonical_event_type."""
        stmt = (
            select(StitchRecord)
            .where(StitchRecord.tenant_id.in_((tenant_id, "*")))
            .order_by(StitchRecord.id.asc())
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        by_id: dict[str, Stitch] = {}
        for r in records:
            if r.id not in by_id or r.tenant_id == tenant_id:
                by_id[r.id] = self._to_domain_model(r)
        return [
            s
            for s in by_id.values()
            if s.canonical_event_type == canonical_event_type and s.is_active
        ]

    async def list_by_mapping_spec_id(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> list[Stitch]:
        """List all Stitches referencing a specific mapping_spec_id."""
        stmt = (
            select(StitchRecord)
            .where(
                StitchRecord.tenant_id.in_((tenant_id, "*")),
                StitchRecord.mapping_spec_id == mapping_spec_id,
            )
            .order_by(StitchRecord.id.asc())
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def delete(
        self,
        *,
        tenant_id: str,
        stitch_id: str,
    ) -> None:
        """Deletes a Stitch record for a tenant."""
        stmt = delete(StitchRecord).where(
            StitchRecord.id == stitch_id,
            StitchRecord.tenant_id == tenant_id,
        )
        await self.session.execute(stmt)


__all__ = ["SqlAlchemyStitchRepository"]
