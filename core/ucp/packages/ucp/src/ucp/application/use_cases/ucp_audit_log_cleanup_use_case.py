import structlog

from ucp.ports.outbound.ucp_audit_log_cleanup_repository_port import (
    IUcpAuditLogCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class UcpAuditLogCleanupUseCase:
    """Application UseCase to clean up old system audit logs."""

    def __init__(self, repository: IUcpAuditLogCleanupRepositoryPort, retention_days: int = 90):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("ucp_audit_log_cleanup_started", retention_days=self.retention_days)
        deleted = await self.repository.cleanup_system_audit_logs(
            retention_days=self.retention_days
        )
        logger.info("ucp_audit_log_cleanup_completed", system_audit_logs_deleted=deleted)
