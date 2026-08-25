import asyncio
import datetime

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from sqlalchemy import delete, select

from config_sync_worker.ports.outbound.edi_control_plane_outbox_cleanup_repository_port import (
    EdiControlPlaneOutboxCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiControlPlaneOutboxCleanupRepository(EdiControlPlaneOutboxCleanupRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def cleanup_control_plane_outbox(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        outbox_deleted = 0
        async for session in self.db_router.get_global_session():
            while True:
                stmt = delete(ControlPlaneOutbox).where(
                    ControlPlaneOutbox.id.in_(
                        select(ControlPlaneOutbox.id)
                        .where(
                            ControlPlaneOutbox.status == "PROCESSED",
                            ControlPlaneOutbox.created_at < cutoff_date,
                        )
                        .limit(5000)
                    )
                )
                from typing import Any, cast

                from sqlalchemy import CursorResult

                res = cast(CursorResult[Any], await session.execute(stmt))
                deleted = res.rowcount
                outbox_deleted += deleted
                await session.commit()
                if deleted < 5000:
                    break
                await asyncio.sleep(0.1)
        return outbox_deleted
