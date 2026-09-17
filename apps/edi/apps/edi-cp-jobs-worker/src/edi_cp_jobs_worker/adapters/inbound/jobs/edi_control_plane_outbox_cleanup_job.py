import structlog
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxCleanupJobHandler:
    def __init__(self, use_case: OutboxCleanerUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_edi_control_plane_outbox_cleanup_job")
        await self.use_case.execute()
