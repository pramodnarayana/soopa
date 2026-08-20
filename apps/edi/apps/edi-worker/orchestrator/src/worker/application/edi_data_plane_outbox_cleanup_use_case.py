import structlog

from worker.ports.edi_data_plane_outbox_cleanup_repository_port import (
    IEdiDataPlaneOutboxCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class EdiDataPlaneOutboxCleanupUseCase:
    """Application UseCase to clean up old PROCESSED EDI Data Plane outbox events."""

    def __init__(
        self, repository: IEdiDataPlaneOutboxCleanupRepositoryPort, retention_days: int = 3
    ):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("edi_data_plane_outbox_cleanup_started", retention_days=self.retention_days)
        await self.repository.cleanup_data_plane_outbox(retention_days=self.retention_days)
        logger.info("edi_data_plane_outbox_cleanup_completed")
