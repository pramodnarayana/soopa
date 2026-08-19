import asyncio
import datetime

import structlog
from database.connection import DatabaseRouter
from database.models.data_plane import AuditLog
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard

from worker.ports.edi_audit_log_cleanup_repository_port import IEdiAuditLogCleanupRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiAuditLogCleanupRepository(IEdiAuditLogCleanupRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_audit_logs(self, retention_days: int, concurrency_limit: int = 5) -> None:
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
                        audit_deleted = 0
                        while True:
                            stmt_audit = delete(AuditLog).where(
                                AuditLog.id.in_(
                                    select(AuditLog.id)
                                    .where(AuditLog.created_at < cutoff_date)
                                    .limit(5000)
                                )
                            )
                            res_audit: CursorResult[tuple[()]] = await session.execute(stmt_audit)  # type: ignore[assignment]
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
            *[_bounded_cleanup(shard.name, shard.dsn) for shard in shards], return_exceptions=True
        )
        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            logger.error("shard_cleanup_had_failures", failure_count=len(exceptions))
            raise exceptions[0]
