import asyncio
import datetime
from typing import Any, cast

import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from sqlalchemy import CursorResult, delete, select

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiControlPlaneOutboxCleanupRepository(OutboxCleanupRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_outbox(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        outbox_deleted = 0
        async for session in self.db_router.get_global_session():
            while True:
                stmt = delete(ControlPlaneOutbox).where(
                    ControlPlaneOutbox.id.in_(
                        select(ControlPlaneOutbox.id)
                        .where(
                            ControlPlaneOutbox.status == OutboxStatus.PROCESSED,
                            ControlPlaneOutbox.created_at < cutoff_date,
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
