import asyncio
import datetime

from platform_orm.models.idempotency import IdempotencyResult
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ucp.ports.ucp_idempotency_cleanup_repository_port import IUcpIdempotencyCleanupRepositoryPort


class SqlAlchemyUcpIdempotencyCleanupRepository(IUcpIdempotencyCleanupRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def cleanup_idempotency_results(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        idempotency_deleted = 0
        async with self.session_factory() as session:
            while True:
                from sqlalchemy import tuple_

                stmt_idempotency = delete(IdempotencyResult).where(
                    tuple_(IdempotencyResult.tenant_id, IdempotencyResult.idempotency_key).in_(
                        select(IdempotencyResult.tenant_id, IdempotencyResult.idempotency_key)
                        .where(IdempotencyResult.created_at < cutoff_date)
                        .limit(5000)
                    )
                )
                res_idempotency: CursorResult[tuple[()]] = await session.execute(stmt_idempotency)  # type: ignore[assignment]
                deleted = res_idempotency.rowcount
                idempotency_deleted += deleted
                await session.commit()
                if deleted < 5000:
                    break
                await asyncio.sleep(0.1)
        return idempotency_deleted
