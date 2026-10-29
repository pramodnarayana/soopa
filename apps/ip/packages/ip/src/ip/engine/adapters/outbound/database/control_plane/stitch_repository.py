"""SQLAlchemy repository adapter for Stitch aggregates in the Control Plane (`ip.stitches`)."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import StitchRecord
from ip.engine.domain.stitch import Stitch
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyStitchRepository(GlobalSqlAlchemyRepository, StitchRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of StitchRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: StitchRecord) -> Stitch:
        return Stitch(
            id=record.id,
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            workflow_version=record.workflow_version,
            canonical_event_type=record.canonical_event_type,
            is_trigger=record.is_trigger,
            condition_event_key=record.condition_event_key,
            idempotency_key_field=record.idempotency_key_field,
            concurrency_key_field=record.concurrency_key_field,
            resource_hint_field=record.resource_hint_field,
            is_active=record.is_active,
        )

    @staticmethod
    def _to_orm_model(stitch: Stitch, now: datetime) -> StitchRecord:
        return StitchRecord(
            id=stitch.id,
            tenant_id=stitch.tenant_id,
            workflow_id=stitch.workflow_id,
            workflow_version=stitch.workflow_version,
            canonical_event_type=stitch.canonical_event_type,
            is_trigger=stitch.is_trigger,
            condition_event_key=stitch.condition_event_key,
            idempotency_key_field=stitch.idempotency_key_field,
            concurrency_key_field=stitch.concurrency_key_field,
            resource_hint_field=stitch.resource_hint_field,
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
        record.tenant_id = stitch.tenant_id
        record.workflow_id = stitch.workflow_id
        record.workflow_version = stitch.workflow_version
        record.canonical_event_type = stitch.canonical_event_type
        record.is_trigger = stitch.is_trigger
        record.condition_event_key = stitch.condition_event_key
        record.idempotency_key_field = stitch.idempotency_key_field
        record.concurrency_key_field = stitch.concurrency_key_field
        record.resource_hint_field = stitch.resource_hint_field
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
            .where(
                StitchRecord.tenant_id.in_((tenant_id, "*")),
                StitchRecord.canonical_event_type == canonical_event_type,
                StitchRecord.is_active.is_(True),
            )
            .order_by(StitchRecord.id.asc())
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        by_id: dict[str, Stitch] = {}
        for r in records:
            if r.id not in by_id or r.tenant_id == tenant_id:
                by_id[r.id] = self._to_domain_model(r)
        return list(by_id.values())


__all__ = ["SqlAlchemyStitchRepository"]
