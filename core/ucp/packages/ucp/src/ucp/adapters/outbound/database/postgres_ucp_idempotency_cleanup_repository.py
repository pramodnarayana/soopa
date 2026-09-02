import asyncio
import datetime
from typing import Any, cast

from database.models.idempotency import IdempotencyResult
from sqlalchemy import delete, select, tuple_
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ucp.ports.outbound.ucp_idempotency_cleanup_repository_port import (
    UcpIdempotencyCleanupRepositoryPort,
)


class SqlAlchemyUcpIdempotencyCleanupRepository(UcpIdempotencyCleanupRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def cleanup_idempotency_results(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        idempotency_deleted = 0
        async with self.session_factory() as session:
            while True:
                stmt_idempotency = delete(IdempotencyResult).where(
                    tuple_(IdempotencyResult.tenant_id, IdempotencyResult.idempotency_key).in_(
                        select(IdempotencyResult.tenant_id, IdempotencyResult.idempotency_key)
                        .where(IdempotencyResult.created_at < cutoff_date)
                        .limit(5000)
                    )
                )
                res_idempotency = cast(CursorResult[Any], await session.execute(stmt_idempotency))
                deleted = res_idempotency.rowcount
                idempotency_deleted += deleted
                await session.commit()
                if deleted < 5000:
                    break
                await asyncio.sleep(0.1)
        return idempotency_deleted
