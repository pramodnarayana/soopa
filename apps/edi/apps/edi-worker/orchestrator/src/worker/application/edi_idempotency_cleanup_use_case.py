import structlog

from worker.ports.edi_idempotency_cleanup_repository_port import (
    IEdiIdempotencyCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class EdiIdempotencyCleanupUseCase:
    """Application UseCase to clean up old EDI Data Plane idempotency results (ProcessedEvents)."""

    def __init__(self, repository: IEdiIdempotencyCleanupRepositoryPort, retention_days: int = 14):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("edi_idempotency_cleanup_started", retention_days=self.retention_days)
        await self.repository.cleanup_idempotency_results(retention_days=self.retention_days)
        logger.info("edi_idempotency_cleanup_completed")
