import asyncio
import datetime

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import ProcessedEvent
from sqlalchemy import delete, select, tuple_
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard

from worker.ports.outbound.edi_idempotency_cleanup_repository_port import (
    EdiIdempotencyCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiIdempotencyCleanupRepository(EdiIdempotencyCleanupRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_idempotency_results(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> None:
        sem = asyncio.Semaphore(concurrency_limit)
        async for global_session in self.db_router.get_global_session():
            res = await global_session.execute(select(DatabaseShard))
            shards = res.scalars().all()

        async def _bounded_cleanup(shard_name: str, shard_dsn: str) -> None:
            async with sem:
                try:
                    cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
                        days=retention_days
                    )
                    engine = await self.db_router.get_engine(shard_name, shard_dsn)
                    async with AsyncSession(engine, expire_on_commit=False) as session:
                        processed_deleted = 0
                        while True:
                            stmt_processed = delete(ProcessedEvent).where(
                                tuple_(
                                    ProcessedEvent.tenant_id, ProcessedEvent.idempotency_key
                                ).in_(
                                    select(ProcessedEvent.tenant_id, ProcessedEvent.idempotency_key)
                                    .where(ProcessedEvent.processed_at < cutoff_date)
                                    .limit(5000)
                                )
                            )
                            res_processed: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
                                stmt_processed
                            )
                            deleted = res_processed.rowcount
                            processed_deleted += deleted
                            await session.commit()
                            if deleted < 5000:
                                break
                            await asyncio.sleep(0.1)
                    logger.info(
                        "shard_idempotency_cleanup_completed",
                        shard_name=shard_name,
                        idempotency_deleted=processed_deleted,
                    )
                except Exception:
                    logger.exception("sweep_shard_idempotency_failed", shard_name=shard_name)
                    raise

        results = await asyncio.gather(
            *[_bounded_cleanup(shard.name, shard.dsn) for shard in shards], return_exceptions=True
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            logger.error("shard_cleanup_had_failures", failure_count=len(exceptions))
            raise exceptions[0]
