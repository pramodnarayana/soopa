import asyncio
import datetime
from typing import Any, cast

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiDataPlaneOutboxCleanupRepository(OutboxCleanupRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_outbox(self, retention_days: int, concurrency_limit: int = 5) -> int:
        sem = asyncio.Semaphore(concurrency_limit)
        shards = await self.db_router.get_all_shards()

        async def _bounded_cleanup(shard_name: str, shard_dsn: str) -> int:
            async with sem:
                try:
                    cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
                        days=retention_days
                    )
                    engine = await self.db_router.get_engine(shard_name, shard_dsn)
                    async with AsyncSession(engine, expire_on_commit=False) as session:
                        outbox_deleted = 0
                        while True:
                            stmt_outbox = delete(DataPlaneOutbox).where(
                                DataPlaneOutbox.id.in_(
                                    select(DataPlaneOutbox.id)
                                    .where(
                                        DataPlaneOutbox.status == "PROCESSED",
                                        DataPlaneOutbox.created_at < cutoff_date,
                                    )
                                    .limit(5000)
                                )
                            )

                            res_outbox = cast(CursorResult[Any], await session.execute(stmt_outbox))
                            deleted = res_outbox.rowcount
                            outbox_deleted += deleted
                            await session.commit()
                            if deleted < 5000:
                                break
                            await asyncio.sleep(0.1)
                    logger.info(
                        "shard_data_plane_outbox_cleanup_completed",
                        shard_name=shard_name,
                        outbox_deleted=outbox_deleted,
                    )
                    return outbox_deleted
                except Exception:
                    logger.exception("sweep_shard_outbox_failed", shard_name=shard_name)
                    raise

        results = await asyncio.gather(
            *[_bounded_cleanup(shard_name, shard_dsn) for shard_name, shard_dsn in shards],
            return_exceptions=True,
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            raise ExceptionGroup("shard_cleanup_had_failures", exceptions)

        return sum(cast(int, result) for result in results)
