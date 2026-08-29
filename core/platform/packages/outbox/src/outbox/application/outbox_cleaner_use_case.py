import structlog
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort

logger = structlog.get_logger(__name__)


class OutboxCleanerUseCase:
    """Application UseCase to clean up old PROCESSED outbox events."""

    def __init__(self, repository: OutboxCleanupRepositoryPort, retention_days: int = 3):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("outbox_cleanup_started", retention_days=self.retention_days)
        deleted = await self.repository.cleanup_outbox(retention_days=self.retention_days)
        logger.info("outbox_cleanup_completed", outbox_deleted=deleted)
