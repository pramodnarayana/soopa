import structlog

from ucp.ports.outbound.ucp_outbox_cleanup_repository_port import IUcpOutboxCleanupRepositoryPort

logger = structlog.get_logger(__name__)


class UcpOutboxCleanupUseCase:
    """Application UseCase to clean up old PROCESSED outbox events."""

    def __init__(self, repository: IUcpOutboxCleanupRepositoryPort, retention_days: int = 3):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("ucp_outbox_cleanup_started", retention_days=self.retention_days)
        deleted = await self.repository.cleanup_outbox(retention_days=self.retention_days)
        logger.info("ucp_outbox_cleanup_completed", outbox_deleted=deleted)
