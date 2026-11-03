import asyncio
import datetime
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from database.models.observability import SystemAuditLog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.ports.outbound.ucp_audit_log_cleanup_repository_port import (
    UcpAuditLogCleanupRepositoryPort,
)


class SqlAlchemyUcpAuditLogCleanupRepository(UcpAuditLogCleanupRepositoryPort):
    def __init__(
        self, session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    ) -> None:
        self.session_factory = session_factory

    async def cleanup_system_audit_logs(self, retention_days: int) -> int:
        cutoff_date = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        ).replace(tzinfo=None)
        audit_deleted = 0
        async with self.session_factory() as session:
            while True:
                stmt_audit = (
                    delete(SystemAuditLog)
                    .where(
                        SystemAuditLog.id.in_(
                            select(SystemAuditLog.id)
                            .where(SystemAuditLog.created_at < cutoff_date)
                            .limit(5000)
                        )
                    )
                    .returning(SystemAuditLog.id)
                )
                res_audit = await session.execute(stmt_audit)
                deleted = len(res_audit.scalars().all())
                audit_deleted += deleted
                await session.commit()
                if deleted < 5000:
                    break
                await asyncio.sleep(0.1)
        return audit_deleted
