import structlog

from worker.ports.edi_control_plane_outbox_cleanup_repository_port import (
    IEdiControlPlaneOutboxCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxCleanupUseCase:
    """Application UseCase to clean up old PROCESSED EDI Control Plane outbox events."""

    def __init__(
        self, repository: IEdiControlPlaneOutboxCleanupRepositoryPort, retention_days: int = 3
    ):
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("edi_control_plane_outbox_cleanup_started", retention_days=self.retention_days)
        deleted = await self.repository.cleanup_control_plane_outbox(
            retention_days=self.retention_days
        )
        logger.info("edi_control_plane_outbox_cleanup_completed", outbox_deleted=deleted)
