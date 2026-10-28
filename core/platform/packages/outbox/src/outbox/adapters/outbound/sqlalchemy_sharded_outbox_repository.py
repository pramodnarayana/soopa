"""Generic SQLAlchemy ORM Sharded Outbox Repository for Multi-Shard Data Planes."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

import structlog
from database.models.common import OutboxMixin
from database.router import DatabaseRouterPort
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import ShardOutboxDrainPort
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    OutboxModelClassProtocol,
    OutboxRecordProtocol,
    map_outbox_row_to_envelope,
)
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.events import EventEnvelope, EventProcessingLane
from sqlalchemy import CursorResult, case, delete, or_, select, update

logger = structlog.get_logger(__name__)


class SqlAlchemyShardedOutboxRepository(
    OutboxRepositoryPort,
    OutboxCleanupRepositoryPort,
    ShardOutboxDrainPort,
):
    """
    Generic SQLAlchemy ORM Outbox repository across all tenant shards for a given `app_slug`
    (e.g., `public.ip_outbox` across `ip_shard_*`).

    Satisfies:
    - `ShardOutboxDrainPort` for `MultiShardOutboxDrainRelay` (0s delay, per-shard bulk completion).
    - `OutboxRepositoryPort` for `OutboxSweeperUseCase` (fallback stuck-lease recovery).
    - `OutboxCleanupRepositoryPort` for `OutboxCleanerUseCase` (chunked retention pruning).
    """

    _SWEEP_BATCH_SIZE: int = 5000

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        *,
        model_cls: type[OutboxMixin],
        app_slug: str,
        source: str,
        max_attempts: int = 5,
    ) -> None:
        self._db_router = db_router
        self._model_cls = cast(type[OutboxModelClassProtocol], model_cls)
        self._orm_cls = model_cls
        self._app_slug = app_slug
        self._source = source
        self._max_attempts = max_attempts
        self._event_shard_map: dict[str, tuple[str, str]] = {}

    async def list_shards(self) -> list[tuple[str, str]]:
        shards = await self._db_router.get_all_shards(app_slug=self._app_slug)
        return list(shards)

    async def claim_shard_events(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        worker_id: str,
        limit: int,
        lock_lease_ms: int,
    ) -> list[EventEnvelope]:
        now = datetime.now(UTC)
        lease_until = now + timedelta(milliseconds=lock_lease_ms)
        m = self._model_cls
        envelopes: list[EventEnvelope] = []

        async for session in self._db_router.get_shard_session(shard_name, shard_dsn):
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

            rows.sort(
                key=lambda r: (
                    0 if r.lane == EventProcessingLane.REALTIME.value else 1,
                    r.created_at,
                )
            )
            for row in rows:
                row_id = str(cast(OutboxRecordProtocol, row).id)
                row_tenant = str(cast(OutboxRecordProtocol, row).tenant_id)
                self._event_shard_map[row_id] = (shard_name, shard_dsn)
                envelopes.append(
                    map_outbox_row_to_envelope(
                        row,
                        record_id=row_id,
                        tenant_id=row_tenant,
                        source=self._source,
                    )
                )
        return envelopes

    async def mark_shard_completed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = self._model_cls
        async for session in self._db_router.get_shard_session(shard_name, shard_dsn):
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
        for eid in event_ids:
            self._event_shard_map.pop(eid, None)

    async def mark_shard_failed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = self._model_cls
        async for session in self._db_router.get_shard_session(shard_name, shard_dsn):
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
        for eid in event_ids:
            self._event_shard_map.pop(eid, None)

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        shards = await self.list_shards()
        for shard_name, shard_dsn in shards:
            remaining = limit - len(events)
            if remaining <= 0:
                break
            claimed = await self.claim_shard_events(
                shard_name=shard_name,
                shard_dsn=shard_dsn,
                worker_id=worker_id,
                limit=remaining,
                lock_lease_ms=lock_lease_ms,
            )
            events.extend(claimed)
        return events

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        await self.mark_completed_batch([event_id], worker_id)

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        if not event_ids:
            return
        by_shard: dict[tuple[str, str], list[str]] = {}
        unknown_ids: list[str] = []
        for eid in event_ids:
            target = self._event_shard_map.get(eid)
            if target is not None:
                by_shard.setdefault(target, []).append(eid)
            else:
                unknown_ids.append(eid)

        for (shard_name, shard_dsn), ids in by_shard.items():
            await self.mark_shard_completed_batch(
                shard_name=shard_name,
                shard_dsn=shard_dsn,
                event_ids=ids,
                worker_id=worker_id,
            )

        if unknown_ids:
            shards = await self.list_shards()
            for shard_name, shard_dsn in shards:
                await self.mark_shard_completed_batch(
                    shard_name=shard_name,
                    shard_dsn=shard_dsn,
                    event_ids=unknown_ids,
                    worker_id=worker_id,
                )

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        await self.mark_failed_batch([event_id], worker_id, error_message)

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        if not event_ids:
            return
        by_shard: dict[tuple[str, str], list[str]] = {}
        unknown_ids: list[str] = []
        for eid in event_ids:
            target = self._event_shard_map.get(eid)
            if target is not None:
                by_shard.setdefault(target, []).append(eid)
            else:
                unknown_ids.append(eid)

        for (shard_name, shard_dsn), ids in by_shard.items():
            await self.mark_shard_failed_batch(
                shard_name=shard_name,
                shard_dsn=shard_dsn,
                event_ids=ids,
                worker_id=worker_id,
                error_message=error_message,
            )

        if unknown_ids:
            shards = await self.list_shards()
            for shard_name, shard_dsn in shards:
                await self.mark_shard_failed_batch(
                    shard_name=shard_name,
                    shard_dsn=shard_dsn,
                    event_ids=unknown_ids,
                    worker_id=worker_id,
                    error_message=error_message,
                )

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        total_swept = 0
        m = self._model_cls
        shards = await self.list_shards()
        for shard_name, shard_dsn in shards:
            async for session in self._db_router.get_shard_session(shard_name, shard_dsn):
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

    async def cleanup_outbox(self, retention_days: int, concurrency_limit: int = 5) -> int:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        if concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be strictly positive")

        sem = asyncio.Semaphore(concurrency_limit)
        shards = await self.list_shards()
        m = self._model_cls

        async def _cleanup_shard(shard_name: str, shard_dsn: str) -> int:
            async with sem:
                cutoff = datetime.now(UTC) - timedelta(days=retention_days)
                shard_deleted = 0
                async for session in self._db_router.get_shard_session(shard_name, shard_dsn):
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
                        shard_deleted += deleted
                        await session.commit()
                        if deleted < self._SWEEP_BATCH_SIZE:
                            break
                        await asyncio.sleep(0.1)
                logger.info(
                    "shard_outbox_cleanup_completed",
                    app_slug=self._app_slug,
                    shard_name=shard_name,
                    outbox_deleted=shard_deleted,
                )
                return shard_deleted

        results = await asyncio.gather(
            *[_cleanup_shard(name, dsn) for name, dsn in shards],
            return_exceptions=True,
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            raise ExceptionGroup("shard_outbox_cleanup_had_failures", exceptions)

        return sum(cast(int, r) for r in results)


__all__ = ["SqlAlchemyShardedOutboxRepository"]
