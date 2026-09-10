import asyncio
import datetime
from typing import cast

from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp_models.events import UcpOutbox


class SqlAlchemyUcpOutboxCleanupRepository(OutboxCleanupRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def cleanup_outbox(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        outbox_deleted = 0
        async with self.session_factory() as session:
            while True:
                stmt_outbox = delete(UcpOutbox).where(
                    UcpOutbox.id.in_(
                        select(UcpOutbox.id)
                        .where(
                            UcpOutbox.status == OutboxStatus.PROCESSED,
                            UcpOutbox.created_at < cutoff_date,
                        )
                        .limit(5000)
                    )
                )
                res_outbox = cast(CursorResult[tuple[()]], await session.execute(stmt_outbox))
                deleted = res_outbox.rowcount
                outbox_deleted += deleted
                await session.commit()
                if deleted < 5000:
                    break
                await asyncio.sleep(0.1)
        return outbox_deleted
