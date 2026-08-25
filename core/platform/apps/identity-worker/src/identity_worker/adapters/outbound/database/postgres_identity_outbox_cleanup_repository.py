import asyncio
import datetime

from platform_orm.models.identity import IdentityOutbox
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from identity_worker.ports.outbound.outbox_cleanup_repository_port import (
    OutboxCleanupRepositoryPort,
)


class PostgresIdentityOutboxCleanupRepository(OutboxCleanupRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def cleanup_outbox(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        batch_size = 5000
        outbox_deleted = 0
        async with self.session_factory() as session:
            while True:
                stmt_outbox = delete(IdentityOutbox).where(
                    IdentityOutbox.id.in_(
                        select(IdentityOutbox.id)
                        .where(
                            IdentityOutbox.status == "COMPLETED",
                            IdentityOutbox.created_at < cutoff_date,
                        )
                        .limit(batch_size)
                    )
                )
                res_outbox: CursorResult[tuple[()]] = await session.execute(stmt_outbox)  # type: ignore[assignment]
                deleted = res_outbox.rowcount
                outbox_deleted += deleted
                await session.commit()
                if deleted < batch_size:
                    break
                await asyncio.sleep(0.1)
        return outbox_deleted
