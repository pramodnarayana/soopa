import structlog
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase

logger = structlog.get_logger(__name__)


class IdentityOutboxCleanupJobHandler:
    """
    Background job that sweeps and deletes outbox events that have already been COMPLETED.
    """

    def __init__(self, use_case: OutboxCleanerUseCase):
        self.use_case = use_case

    async def execute(self) -> None:
        try:
            logger.info("identity_outbox_cleanup_started")
            await self.use_case.execute()
            logger.info("identity_outbox_cleanup_completed")
        except Exception:
            logger.exception("identity_outbox_cleanup_failed")
            raise
