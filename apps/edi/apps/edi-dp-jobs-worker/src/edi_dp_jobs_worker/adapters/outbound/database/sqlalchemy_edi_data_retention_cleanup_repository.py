import asyncio
import datetime
from collections.abc import Callable
from typing import Any, cast

import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import ProcessedEvent, TraceEvent
from sqlalchemy import CursorResult, Delete, delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from edi_dp_jobs_worker.ports.outbound.edi_data_retention_cleanup_repository_port import (
    EdiDataRetentionCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)

_StmtFactory = Callable[[datetime.datetime], Delete]


class SqlAlchemyEdiDataRetentionCleanupRepository(EdiDataRetentionCleanupRepositoryPort):
    _BATCH_SIZE: int = 5000

    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> None:
        def _stmt_factory(cutoff: datetime.datetime) -> Delete:
            return delete(ProcessedEvent).where(
                tuple_(ProcessedEvent.tenant_id, ProcessedEvent.idempotency_key).in_(
                    select(ProcessedEvent.tenant_id, ProcessedEvent.idempotency_key)
                    .where(ProcessedEvent.processed_at < cutoff)
                    .limit(self._BATCH_SIZE)
                )
            )

        await self._cleanup_all_shards(
            retention_days=retention_days,
            concurrency_limit=concurrency_limit,
            stmt_factory=_stmt_factory,
            log_label="processed_events",
            count_key="idempotency_deleted",
        )

    async def cleanup_trace_events(self, retention_days: int, concurrency_limit: int = 5) -> None:
        def _stmt_factory(cutoff: datetime.datetime) -> Delete:
            return delete(TraceEvent).where(
                TraceEvent.id.in_(
                    select(TraceEvent.id)
                    .where(TraceEvent.created_at < cutoff)
                    .limit(self._BATCH_SIZE)
                )
            )

        await self._cleanup_all_shards(
            retention_days=retention_days,
            concurrency_limit=concurrency_limit,
            stmt_factory=_stmt_factory,
            log_label="trace_events",
            count_key="trace_events_deleted",
        )

    async def _cleanup_all_shards(
        self,
        retention_days: int,
        concurrency_limit: int,
        stmt_factory: _StmtFactory,
        log_label: str,
        count_key: str,
    ) -> None:
        if concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be strictly positive")

        sem = asyncio.Semaphore(concurrency_limit)
        shards = await self.db_router.get_all_shards()

        async def _bounded_cleanup(shard_name: str, shard_dsn: str) -> None:
            async with sem:
                try:
                    cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
                        days=retention_days
                    )
                    async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                        deleted_total = await self._delete_in_batches(
                            session, stmt_factory, cutoff_date
                        )

                    logger.info(
                        "shard_cleanup_completed",
                        log_label=log_label,
                        shard_name=shard_name,
                        **{count_key: deleted_total},
                    )
                except Exception:
                    logger.exception(
                        "sweep_shard_cleanup_failed", log_label=log_label, shard_name=shard_name
                    )
                    raise

        results = await asyncio.gather(
            *[_bounded_cleanup(shard_name, shard_dsn) for shard_name, shard_dsn in shards],
            return_exceptions=True,
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            raise ExceptionGroup("shard_cleanup_had_failures", exceptions)

    async def _delete_in_batches(
        self,
        session: AsyncSession,
        stmt_factory: _StmtFactory,
        cutoff_date: datetime.datetime,
    ) -> int:
        deleted_total = 0
        while True:
            res = cast(CursorResult[Any], await session.execute(stmt_factory(cutoff_date)))
            deleted = res.rowcount
            deleted_total += deleted
            await session.commit()
            if deleted < self._BATCH_SIZE:
                break
            await asyncio.sleep(0.1)
        return deleted_total
