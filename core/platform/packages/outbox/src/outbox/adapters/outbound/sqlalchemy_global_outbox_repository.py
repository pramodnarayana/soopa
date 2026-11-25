"""Generic SQLAlchemy ORM Outbox Repository and Cleanup Adapter for Global Control Plane schemas."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Generic, TypeVar

import structlog
from database.models.common import OutboxMixin
from database.outbox_serializer import map_outbox_row_to_envelope
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.events import EventEnvelope, EventProcessingLane
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

OutboxModelT = TypeVar("OutboxModelT", bound=OutboxMixin)
SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlAlchemyGlobalOutboxRepository(
    OutboxRepositoryPort, OutboxCleanupRepositoryPort, Generic[OutboxModelT]
):
    """
    Generic SQLAlchemy 2.0 ORM Outbox repository for a Bounded Context's Global DB outbox table
    (e.g. `identity.outbox`, `notifications.notification_outbox`). Zero raw SQL `text()` queries.
    """

    _SWEEP_BATCH_SIZE: int = 5000
    _BASE_RETRY_BACKOFF_SECONDS: int = 10
    _MAX_RETRY_BACKOFF_SECONDS: int = 300

    def __init__(
        self,
        *,
        session_factory: SessionScopeFactory,
        model_cls: type[OutboxModelT],
        source: str,
        max_attempts: int = 3,
        event_types: Sequence[str] | None = None,
        exclude_event_types: Sequence[str] | None = None,
        lanes: Sequence[str] | None = None,
        base_retry_backoff_seconds: int = _BASE_RETRY_BACKOFF_SECONDS,
        max_retry_backoff_seconds: int = _MAX_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._session_scope = session_factory
        self._model_cls = model_cls
        self._source = source
        self._max_attempts = max_attempts
        self._event_types: tuple[str, ...] | None = (
            tuple(event_types) if event_types is not None else None
        )
        self._exclude_event_types: tuple[str, ...] | None = (
            tuple(exclude_event_types) if exclude_event_types is not None else None
        )
        self._lanes: tuple[str, ...] | None = tuple(lanes) if lanes is not None else None
        self._base_retry_backoff_seconds = base_retry_backoff_seconds
        self._max_retry_backoff_seconds = max_retry_backoff_seconds

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        now = datetime.now(UTC)
        lease_until = now + timedelta(milliseconds=lock_lease_ms)
        m = self._model_cls

        async with self._session_scope() as session:
            retry_ready = or_(m.lease_expires_at.is_(None), m.lease_expires_at <= now)
            subq_stmt = select(m.id).where(
                or_(
                    (m.status == OutboxStatus.PENDING.value) & retry_ready,
                    (m.status == OutboxStatus.PROCESSING.value) & (m.lease_expires_at < now),
                )
            )
            if self._event_types is not None:
                subq_stmt = subq_stmt.where(m.event_type.in_(self._event_types))
            if self._exclude_event_types is not None:
                subq_stmt = subq_stmt.where(m.event_type.not_in(self._exclude_event_types))
            if self._lanes is not None:
                subq_stmt = subq_stmt.where(m.lane.in_(self._lanes))

            claimed_cte = (
                subq_stmt.order_by(m.lane.desc(), m.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
                .cte("claimed_global_outbox_rows")
            )

            stmt = (
                update(m)
                .where(m.id == claimed_cte.c.id)
                .values(
                    status=OutboxStatus.PROCESSING.value,
                    updated_at=now,
                    lease_expires_at=lease_until,
                    owner_token=worker_id,
                )
                .returning(m)
            )
            res = await session.execute(stmt)
            rows = list(res.scalars().all())
            await session.commit()

            rows.sort(
                key=lambda r: (
                    0 if r.lane == EventProcessingLane.REALTIME.value else 1,
                    r.created_at,
                )
            )
            return [map_outbox_row_to_envelope(row, source=self._source) for row in rows]

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        total_swept = 0
        m = self._model_cls
        async with self._session_scope() as session:
            while True:
                now = datetime.now(UTC)
                stale_cutoff = now - timedelta(milliseconds=lock_lease_ms)
                sweep_cte = (
                    select(m.id)
                    .where(
                        m.status == OutboxStatus.PROCESSING.value,
                        or_(
                            m.lease_expires_at < now,
                            (m.lease_expires_at.is_(None)) & (m.updated_at <= stale_cutoff),
                        ),
                    )
                    .limit(self._SWEEP_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                    .cte("swept_global_outbox_rows")
                )
                stmt = (
                    update(m)
                    .where(m.id == sweep_cte.c.id)
                    .values(
                        status=OutboxStatus.PENDING.value,
                        lease_expires_at=None,
                        owner_token=None,
                        updated_at=now,
                    )
                    .returning(m.id)
                )
                res = await session.execute(stmt)
                swept = len(res.scalars().all())
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
        async with self._session_scope() as session:
            stmt = (
                update(m)
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
        async with self._session_scope() as session:
            next_status = case(
                (m.attempts + 1 >= self._max_attempts, OutboxStatus.FAILED.value),
                else_=OutboxStatus.PENDING.value,
            )
            if self._base_retry_backoff_seconds <= 0:
                next_retry_at: object = None
            else:
                capped_secs = func.least(
                    self._max_retry_backoff_seconds,
                    self._base_retry_backoff_seconds * func.power(2, m.attempts),
                )
                backoff_expr = func.now() + func.make_interval(0, 0, 0, 0, 0, 0, capped_secs)
                next_retry_at = case(
                    (m.attempts + 1 >= self._max_attempts, None),
                    else_=backoff_expr,
                )
            stmt = (
                update(m)
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
                    lease_expires_at=next_retry_at,
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
        async with self._session_scope() as session:
            while True:
                delete_cte = (
                    select(m.id)
                    .where(
                        m.status.in_((OutboxStatus.PROCESSED.value, OutboxStatus.COMPLETED.value)),
                        m.created_at < cutoff,
                    )
                    .limit(self._SWEEP_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                    .cte("deleted_global_outbox_rows")
                )
                stmt = delete(m).where(m.id == delete_cte.c.id).returning(m.id)
                res = await session.execute(stmt)
                deleted = len(res.scalars().all())
                total_deleted += deleted
                await session.commit()
                if deleted < self._SWEEP_BATCH_SIZE:
                    break
                await asyncio.sleep(0.1)
        return total_deleted


__all__ = ["SessionScopeFactory", "SqlAlchemyGlobalOutboxRepository"]
