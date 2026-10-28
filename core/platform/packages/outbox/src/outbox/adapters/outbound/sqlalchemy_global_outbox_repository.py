"""Generic SQLAlchemy ORM Outbox Repository and Cleanup Adapter for Global Control Plane schemas."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import structlog
from database.models.common import OutboxMixin
from database.router import DatabaseRouterPort
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane
from sqlalchemy import CursorResult, case, delete, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute

logger = structlog.get_logger(__name__)


class OutboxRecordProtocol(Protocol):
    """Structural protocol for any SQLAlchemy ORM model inheriting from OutboxMixin + id/tenant_id."""

    id: str
    tenant_id: str
    idempotency_key: str
    event_type: str
    trace_id: str | None
    correlation_id: str | None
    lane: str
    payload: JsonDict


class OutboxModelClassProtocol(Protocol):
    """Class-level SQLAlchemy InstrumentedAttribute protocol for OutboxMixin ORM models."""

    id: InstrumentedAttribute[str]
    tenant_id: InstrumentedAttribute[str]
    idempotency_key: InstrumentedAttribute[str]
    event_type: InstrumentedAttribute[str]
    trace_id: InstrumentedAttribute[str | None]
    correlation_id: InstrumentedAttribute[str | None]
    lane: InstrumentedAttribute[str]
    payload: InstrumentedAttribute[JsonDict]
    status: InstrumentedAttribute[str]
    attempts: InstrumentedAttribute[int]
    published_at: InstrumentedAttribute[datetime | None]
    error_reason: InstrumentedAttribute[str | None]
    created_at: InstrumentedAttribute[datetime]
    updated_at: InstrumentedAttribute[datetime]
    owner_token: InstrumentedAttribute[str | None]
    lease_expires_at: InstrumentedAttribute[datetime | None]


def map_outbox_row_to_envelope(
    row: OutboxMixin, *, record_id: str, tenant_id: str | None, source: str
) -> EventEnvelope:
    """Maps an OutboxMixin ORM instance to a global seedwork.events.EventEnvelope."""
    raw_lane = (
        row.lane if isinstance(row.lane, str) and row.lane else EventProcessingLane.REALTIME.value
    )
    try:
        lane = EventProcessingLane(raw_lane)
    except ValueError:
        lane = EventProcessingLane.REALTIME

    return EventEnvelope(
        id=str(record_id),
        source=source,
        event_type=str(row.event_type),
        tenant_id=str(tenant_id) if tenant_id else None,
        idempotency_key=str(row.idempotency_key) if row.idempotency_key else None,
        payload=dict(row.payload) if isinstance(row.payload, dict) else {},
        trace_id=str(row.trace_id) if row.trace_id else None,
        correlation_id=str(row.correlation_id) if row.correlation_id else None,
        lane=lane,
    )


class SqlAlchemyGlobalOutboxRepository(OutboxRepositoryPort, OutboxCleanupRepositoryPort):
    """
    Generic SQLAlchemy ORM Outbox repository for a Bounded Context's Global DB outbox table
    (e.g. `ip.outbox`). Zero raw SQL `text()` queries.
    """

    _SWEEP_BATCH_SIZE: int = 5000

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        *,
        model_cls: type[OutboxMixin],
        source: str,
        max_attempts: int = 3,
    ) -> None:
        self._db_router = db_router
        self._model_cls = cast(type[OutboxModelClassProtocol], model_cls)
        self._orm_cls = model_cls
        self._source = source
        self._max_attempts = max_attempts

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        now = datetime.now(UTC)
        lease_until = now + timedelta(milliseconds=lock_lease_ms)
        m = self._model_cls

        async with asynccontextmanager(self._db_router.get_global_session)() as session:
            subq = (
                select(m.id)
                .where(
                    or_(
                        m.status == OutboxStatus.PENDING.value,
                        (m.status == OutboxStatus.PROCESSING.value) & (m.lease_expires_at < now),
                    )
                )
                .order_by(m.lane.desc(), m.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )

            stmt = (
                update(self._orm_cls)
                .where(m.id.in_(subq))
                .values(
                    status=OutboxStatus.PROCESSING.value,
                    updated_at=now,
                    lease_expires_at=lease_until,
                    owner_token=worker_id,
                )
                .returning(self._orm_cls)
            )
            res = await session.execute(stmt)
            rows = list(res.scalars().all())
            await session.commit()

            # Sort returned rows in priority order (lane DESC, created_at ASC)
            rows.sort(
                key=lambda r: (
                    0 if r.lane == EventProcessingLane.REALTIME.value else 1,
                    r.created_at,
                )
            )
            envelopes: list[EventEnvelope] = []
            for row in rows:
                row_id = str(cast(OutboxRecordProtocol, row).id)
                row_tenant = str(cast(OutboxRecordProtocol, row).tenant_id)
                envelopes.append(
                    map_outbox_row_to_envelope(
                        row,
                        record_id=row_id,
                        tenant_id=row_tenant,
                        source=self._source,
                    )
                )
            return envelopes

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        total_swept = 0
        m = self._model_cls
        async with asynccontextmanager(self._db_router.get_global_session)() as session:
            while True:
                now = datetime.now(UTC)
                subq = (
                    select(m.id)
                    .where(
                        m.status == OutboxStatus.PROCESSING.value,
                        m.lease_expires_at < now,
                    )
                    .limit(self._SWEEP_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                    .scalar_subquery()
                )
                stmt = (
                    update(self._orm_cls)
                    .where(m.id.in_(subq))
                    .values(
                        status=OutboxStatus.PENDING.value,
                        lease_expires_at=None,
                        owner_token=None,
                        updated_at=now,
                    )
                )
                res = cast(CursorResult[tuple[()]], await session.execute(stmt))
                swept = int(res.rowcount or 0)
                total_swept += swept
                await session.commit()
                if swept < self._SWEEP_BATCH_SIZE:
                    break
                await asyncio.sleep(0.1)
        return total_swept

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        await self.mark_completed_batch([event_id], worker_id)

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = self._model_cls
        async with asynccontextmanager(self._db_router.get_global_session)() as session:
            stmt = (
                update(self._orm_cls)
                .where(
                    m.id.in_(list(event_ids)),
                    m.status == OutboxStatus.PROCESSING.value,
                    m.owner_token == worker_id,
                )
                .values(
                    status=OutboxStatus.PROCESSED.value,
                    published_at=now,
                    updated_at=now,
                    lease_expires_at=None,
                    owner_token=None,
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        await self.mark_failed_batch([event_id], worker_id, error_message)

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = self._model_cls
        async with asynccontextmanager(self._db_router.get_global_session)() as session:
            next_status = case(
                (m.attempts + 1 >= self._max_attempts, OutboxStatus.FAILED.value),
                else_=OutboxStatus.PENDING.value,
            )
            stmt = (
                update(self._orm_cls)
                .where(
                    m.id.in_(list(event_ids)),
                    m.status == OutboxStatus.PROCESSING.value,
                    m.owner_token == worker_id,
                )
                .values(
                    status=next_status,
                    attempts=m.attempts + 1,
                    error_reason=error_message,
                    updated_at=now,
                    lease_expires_at=None,
                    owner_token=None,
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def cleanup_outbox(self, retention_days: int) -> int:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        total_deleted = 0
        m = self._model_cls
        async with asynccontextmanager(self._db_router.get_global_session)() as session:
            while True:
                subq = (
                    select(m.id)
                    .where(
                        m.status == OutboxStatus.PROCESSED.value,
                        m.created_at < cutoff,
                    )
                    .limit(self._SWEEP_BATCH_SIZE)
                    .scalar_subquery()
                )
                stmt = delete(self._orm_cls).where(m.id.in_(subq))
                res = cast(CursorResult[tuple[()]], await session.execute(stmt))
                deleted = int(res.rowcount or 0)
                total_deleted += deleted
                await session.commit()
                if deleted < self._SWEEP_BATCH_SIZE:
                    break
                await asyncio.sleep(0.1)
        return total_deleted


__all__ = [
    "OutboxModelClassProtocol",
    "OutboxRecordProtocol",
    "SqlAlchemyGlobalOutboxRepository",
    "map_outbox_row_to_envelope",
]
