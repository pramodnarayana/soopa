import asyncio
import datetime
from typing import Any, cast

from database.models.identity import IdentityOutbox
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyIdentityOutboxCleanupRepository(OutboxCleanupRepositoryPort):
    """
    Infrastructure adapter for cleaning up processed events from the identity.outbox table.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def cleanup_outbox(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        outbox_deleted = 0
        async with self.session_factory() as session:
            while True:
                stmt = delete(IdentityOutbox).where(
                    IdentityOutbox.id.in_(
                        select(IdentityOutbox.id)
                        .where(
                            IdentityOutbox.status == OutboxStatus.COMPLETED,
                            IdentityOutbox.created_at < cutoff_date,
                        )
                        .limit(5000)
                    )
                )
                res = cast(CursorResult[Any], await session.execute(stmt))
                deleted = res.rowcount
                outbox_deleted += deleted
                await session.commit()
                if deleted < 5000:
                    break
                await asyncio.sleep(0.1)
        return outbox_deleted
