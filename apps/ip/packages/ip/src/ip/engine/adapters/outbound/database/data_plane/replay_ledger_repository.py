"""SQLAlchemy repository adapter for IP Replay Audit Ledger (`ip_replay_ledger`)."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import IpReplayLedgerModel
from ip.engine.domain.replay.models import IpReplayLedgerRecord
from ip.engine.domain.replay.ports import IpReplayLedgerRepositoryPort
from replay.domain.enums import ReplayStage, ReplayStatus, ReplayTargetType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyReplayLedgerRepository(
    TenantSqlAlchemyRepository,
    IpReplayLedgerRepositoryPort,
):
    """Persists and queries Replay Audit Ledger records for the Integration Platform."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: IpReplayLedgerModel) -> IpReplayLedgerRecord:
        """Strict type-safe Data Mapper from ORM model to Domain Aggregate/Record."""
        return IpReplayLedgerRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            idempotency_key=orm.idempotency_key,
            target_type=ReplayTargetType(orm.target_type),
            target_id=orm.target_id,
            target_stage=ReplayStage(orm.target_stage),
            trace_id=orm.trace_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            correlation_id=orm.correlation_id,
            actor=orm.actor,
            reason=orm.reason,
            payload_override=orm.payload_override,
            affected_records=int(orm.affected_records),
            status=ReplayStatus(orm.status),
            error_message=orm.error_message,
            created_at=orm.created_at,
            completed_at=orm.completed_at,
        )

    @staticmethod
    def _to_orm_model(domain: IpReplayLedgerRecord) -> IpReplayLedgerModel:
        """Strict type-safe Data Mapper from Domain Record to ORM model."""
        return IpReplayLedgerModel(
            id=domain.id,
            tenant_id=domain.tenant_id,
            idempotency_key=domain.idempotency_key,
            target_type=domain.target_type.value,
            target_id=domain.target_id,
            target_stage=domain.target_stage.value,
            trace_id=domain.trace_id,
            parent_trace_id=domain.parent_trace_id,
            original_trace_id=domain.original_trace_id,
            correlation_id=domain.correlation_id,
            actor=domain.actor,
            reason=domain.reason,
            payload_override=domain.payload_override,
            affected_records=domain.affected_records,
            status=domain.status.value,
            error_message=domain.error_message,
            created_at=domain.created_at,
            completed_at=domain.completed_at,
        )

    @staticmethod
    def _update_orm_from_domain(orm: IpReplayLedgerModel, domain: IpReplayLedgerRecord) -> None:
        """Updates an existing ORM model from the Domain Record via explicit dot notation."""
        orm.status = domain.status.value
        orm.affected_records = domain.affected_records
        orm.error_message = domain.error_message
        orm.completed_at = domain.completed_at

    async def save(self, record: IpReplayLedgerRecord) -> None:
        stmt = select(IpReplayLedgerModel).where(
            IpReplayLedgerModel.id == record.id,
            IpReplayLedgerModel.tenant_id == record.tenant_id,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            self._session.add(self._to_orm_model(record))
        else:
            self._update_orm_from_domain(existing, record)

        await self._session.flush()

    async def get_by_id(self, replay_id: str, tenant_id: str) -> IpReplayLedgerRecord | None:
        stmt = select(IpReplayLedgerModel).where(
            IpReplayLedgerModel.id == replay_id,
            IpReplayLedgerModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> IpReplayLedgerRecord | None:
        stmt = select(IpReplayLedgerModel).where(
            IpReplayLedgerModel.tenant_id == tenant_id,
            IpReplayLedgerModel.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def list_by_target(
        self,
        tenant_id: str,
        target_type: ReplayTargetType,
        target_id: str,
        limit: int = 50,
    ) -> tuple[IpReplayLedgerRecord, ...]:
        stmt = (
            select(IpReplayLedgerModel)
            .where(
                IpReplayLedgerModel.tenant_id == tenant_id,
                IpReplayLedgerModel.target_type == target_type.value,
                IpReplayLedgerModel.target_id == target_id,
            )
            .order_by(IpReplayLedgerModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        scalars: Sequence[IpReplayLedgerModel] = result.scalars().all()
        return tuple(self._to_domain_model(orm) for orm in scalars)
