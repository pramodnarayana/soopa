import structlog

from edi_background_worker.ports.outbound.edi_audit_log_cleanup_repository_port import (
    EdiAuditLogCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class EdiAuditLogCleanupUseCase:
    """Application UseCase to clean up old EDI Data Plane audit logs."""

    def __init__(self, repository: EdiAuditLogCleanupRepositoryPort, retention_days: int = 90):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("edi_audit_log_cleanup_started", retention_days=self.retention_days)
        await self.repository.cleanup_audit_logs(retention_days=self.retention_days)
        logger.info("edi_audit_log_cleanup_completed")
