import structlog

from ucp.ports.ucp_idempotency_cleanup_repository_port import IUcpIdempotencyCleanupRepositoryPort

logger = structlog.get_logger(__name__)


class UcpIdempotencyCleanupUseCase:
    """Application UseCase to clean up old idempotency results."""

    def __init__(self, repository: IUcpIdempotencyCleanupRepositoryPort, retention_days: int = 7):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("ucp_idempotency_cleanup_started", retention_days=self.retention_days)
        deleted = await self.repository.cleanup_idempotency_results(
            retention_days=self.retention_days
        )
        logger.info("ucp_idempotency_cleanup_completed", idempotency_results_deleted=deleted)
