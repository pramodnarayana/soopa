"""Generic SQLAlchemy ORM Sharded Trace & ProcessedEvent Retention Repository."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import structlog
from database.models.common import ProcessedEventMixin
from database.router import DatabaseRouterPort
from sqlalchemy import CursorResult, Delete, delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from strace.adapters.orm import TraceEventMixin
from strace.ports.retention_repository_port import TraceRetentionRepositoryPort

logger = structlog.get_logger(__name__)

_DeleteStmtFactory = Callable[[datetime], Delete]


class TraceEventRetentionModelProtocol(Protocol):
    """Class-level SQLAlchemy protocol for TraceEventMixin ORM models."""

    id: InstrumentedAttribute[str]
    created_at: InstrumentedAttribute[datetime]


class ProcessedEventRetentionModelProtocol(Protocol):
    """Class-level SQLAlchemy protocol for ProcessedEventMixin ORM models."""

    tenant_id: InstrumentedAttribute[str]
    idempotency_key: InstrumentedAttribute[str]
    processed_at: InstrumentedAttribute[datetime]


class SqlAlchemyShardedTraceRetentionRepository(TraceRetentionRepositoryPort):
    """
    Generic chunked retention cleaner for `trace_events` and `processed_events` across
    all tenant shards for a given `app_slug`.
    """

    _BATCH_SIZE: int = 5000

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        *,
        app_slug: str,
        trace_event_model_cls: type[TraceEventMixin],
        processed_event_model_cls: type[ProcessedEventMixin] | None = None,
    ) -> None:
        self._db_router = db_router
        self._app_slug = app_slug
        self._trace_orm_cls = trace_event_model_cls
        self._trace_cls = cast(type[TraceEventRetentionModelProtocol], trace_event_model_cls)
        self._processed_orm_cls = processed_event_model_cls
        self._processed_cls = (
            cast(type[ProcessedEventRetentionModelProtocol], processed_event_model_cls)
            if processed_event_model_cls is not None
            else None
        )

    async def cleanup_trace_events(self, retention_days: int, concurrency_limit: int = 5) -> int:
        t = self._trace_cls

        def _stmt_factory(cutoff: datetime) -> Delete:
            subq = select(t.id, t.created_at).where(t.created_at < cutoff).limit(self._BATCH_SIZE)
            return delete(self._trace_orm_cls).where(tuple_(t.id, t.created_at).in_(subq))

        return await self._cleanup_all_shards(
            retention_days=retention_days,
            concurrency_limit=concurrency_limit,
            stmt_factory=_stmt_factory,
            log_label="trace_events",
        )

    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> int:
        if self._processed_orm_cls is None or self._processed_cls is None:
            return 0
        p = self._processed_cls
        orm_cls = self._processed_orm_cls

        def _stmt_factory(cutoff: datetime) -> Delete:
            subq = (
                select(p.tenant_id, p.idempotency_key)
                .where(p.processed_at < cutoff)
                .limit(self._BATCH_SIZE)
            )
            return delete(orm_cls).where(tuple_(p.tenant_id, p.idempotency_key).in_(subq))

        return await self._cleanup_all_shards(
            retention_days=retention_days,
            concurrency_limit=concurrency_limit,
            stmt_factory=_stmt_factory,
            log_label="processed_events",
        )

    async def _cleanup_all_shards(
        self,
        *,
        retention_days: int,
        concurrency_limit: int,
        stmt_factory: _DeleteStmtFactory,
        log_label: str,
    ) -> int:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        if concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be strictly positive")

        sem = asyncio.Semaphore(concurrency_limit)
        shards = await self._db_router.get_all_shards(app_slug=self._app_slug)

        async def _bounded_cleanup(shard_name: str, shard_dsn: str) -> int:
            async with sem:
                cutoff = datetime.now(UTC) - timedelta(days=retention_days)
                deleted_total = 0
                async for session in self._db_router.get_shard_session(shard_name, shard_dsn):
                    deleted_total += await self._delete_in_batches(session, stmt_factory, cutoff)
                logger.info(
                    "shard_retention_cleanup_completed",
                    app_slug=self._app_slug,
                    log_label=log_label,
                    shard_name=shard_name,
                    deleted_count=deleted_total,
                )
                return deleted_total

        results = await asyncio.gather(
            *[_bounded_cleanup(name, dsn) for name, dsn in shards],
            return_exceptions=True,
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            raise ExceptionGroup("shard_retention_cleanup_had_failures", exceptions)

        return sum(cast(int, r) for r in results)

    async def _delete_in_batches(
        self,
        session: AsyncSession,
        stmt_factory: _DeleteStmtFactory,
        cutoff: datetime,
    ) -> int:
        deleted_total = 0
        while True:
            res = cast(CursorResult[tuple[()]], await session.execute(stmt_factory(cutoff)))
            deleted = int(res.rowcount or 0)
            deleted_total += deleted
            await session.commit()
            if deleted < self._BATCH_SIZE:
                break
            await asyncio.sleep(0.1)
        return deleted_total


__all__ = ["SqlAlchemyShardedTraceRetentionRepository"]
