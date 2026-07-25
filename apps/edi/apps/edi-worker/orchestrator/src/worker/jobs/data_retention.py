import asyncio
import datetime
import logging

from database.connection import DatabaseRouter
from database.models.control_plane import DatabaseShard
from database.models.data_plane import DataPlaneOutbox, ProcessedEvent
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from worker.core.scheduler.handler import JobHandlerPort
from worker.core.scheduler.models import Job

logger = logging.getLogger(__name__)

_CONCURRENCY_LIMIT = 5
_RETENTION_DAYS = 7


class DataRetentionCleanupJobHandler(JobHandlerPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def execute(self, job: Job) -> datetime.datetime | None:
        """
        Cleans up old PROCESSED outbox events and processed idempotency keys
        across all tenant shards to prevent unbounded database growth.
        """
        logger.info(f"[DataRetentionCleanup] Running sweep for job {job.id}")

        sem = asyncio.Semaphore(_CONCURRENCY_LIMIT)

        async for global_session in self.db_router.get_global_session():
            res = await global_session.execute(select(DatabaseShard))
            shards = res.scalars().all()

        async def _bounded_cleanup(shard_name: str, shard_dsn: str) -> tuple[int, int]:
            async with sem:
                try:
                    return await self._cleanup_shard(shard_name, shard_dsn)
                except Exception as e:
                    logger.error(f"[DataRetentionCleanup] Failed cleaning shard {shard_name}: {e}")
                    raise

        results = await asyncio.gather(
            *[_bounded_cleanup(shard.name, shard.dsn) for shard in shards]
        )

        total_outbox = sum(r[0] for r in results)
        total_processed = sum(r[1] for r in results)

        logger.info(
            f"[DataRetentionCleanup] Cleanup complete. "
            f"Deleted {total_outbox} outbox rows and {total_processed} processed_events rows."
        )

        # Return None to let the scheduler calculate the next run based on interval
        return None

    async def _cleanup_shard(self, shard_name: str, shard_dsn: str) -> tuple[int, int]:
        """Sweep a single tenant shard, deleting old records."""
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=_RETENTION_DAYS)

        engine = await self.db_router.get_engine(shard_name, shard_dsn)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            # Delete old PROCESSED outbox events
            stmt_outbox = delete(DataPlaneOutbox).where(
                DataPlaneOutbox.status == "PROCESSED",
                DataPlaneOutbox.created_at < cutoff_date,
            )
            res_outbox: CursorResult[tuple[()]] = await session.execute(stmt_outbox)  # type: ignore[assignment]
            outbox_deleted: int = res_outbox.rowcount

            # Delete old processed_events
            stmt_processed = delete(ProcessedEvent).where(ProcessedEvent.processed_at < cutoff_date)
            res_processed: CursorResult[tuple[()]] = await session.execute(stmt_processed)  # type: ignore[assignment]
            processed_deleted: int = res_processed.rowcount

            await session.commit()

        return outbox_deleted, processed_deleted
