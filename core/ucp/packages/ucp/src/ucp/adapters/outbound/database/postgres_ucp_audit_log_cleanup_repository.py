import asyncio
import datetime

from platform_orm.models.observability import SystemAuditLog
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ucp.ports.ucp_audit_log_cleanup_repository_port import IUcpAuditLogCleanupRepositoryPort


class SqlAlchemyUcpAuditLogCleanupRepository(IUcpAuditLogCleanupRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def cleanup_system_audit_logs(self, retention_days: int) -> int:
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        audit_deleted = 0
        async with self.session_factory() as session:
            while True:
                stmt_audit = delete(SystemAuditLog).where(
                    SystemAuditLog.id.in_(
                        select(SystemAuditLog.id)
                        .where(SystemAuditLog.created_at < cutoff_date)
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
        return audit_deleted
