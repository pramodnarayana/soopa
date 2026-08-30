import asyncio
import datetime
from typing import Any, cast

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import AuditLog
from sqlalchemy import CursorResult, delete, select

from edi_background_worker.ports.outbound.edi_audit_log_cleanup_repository_port import (
    EdiAuditLogCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiAuditLogCleanupRepository(EdiAuditLogCleanupRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_audit_logs(self, retention_days: int, concurrency_limit: int = 5) -> None:
        sem = asyncio.Semaphore(concurrency_limit)
        shards = await self.db_router.get_all_shards()

        async def _bounded_cleanup(shard_name: str, shard_dsn: str) -> None:
            async with sem:
                try:
                    cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
                        days=retention_days
                    )
                    async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                        audit_deleted = 0
                        while True:
                            stmt_audit = delete(AuditLog).where(
                                AuditLog.id.in_(
                                    select(AuditLog.id)
                                    .where(AuditLog.created_at < cutoff_date)
                                    .limit(5000)
                                )
                            )

                            res_audit = cast(CursorResult[Any], await session.execute(stmt_audit))
                            deleted = res_audit.rowcount
                            audit_deleted += deleted
                            await session.commit()
                            if deleted < 5000:
                                break
                            await asyncio.sleep(0.1)
                    logger.info(
                        "shard_audit_log_cleanup_completed",
                        shard_name=shard_name,
                        audit_deleted=audit_deleted,
                    )
                except Exception:
                    logger.exception("sweep_shard_audit_log_failed", shard_name=shard_name)
                    raise

        results = await asyncio.gather(
            *[_bounded_cleanup(shard_name, shard_dsn) for shard_name, shard_dsn in shards],
            return_exceptions=True,
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            raise ExceptionGroup("shard_cleanup_had_failures", exceptions)
