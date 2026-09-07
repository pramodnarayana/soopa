import structlog
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase

logger = structlog.get_logger(__name__)


class NotificationOutboxCleanupJobHandler:
    """
    Background job that deletes outbox events that have already been PROCESSED.
    Triggered by the scheduler via the notification-jobs SQS queue.
    """

    def __init__(self, use_case: OutboxCleanerUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        try:
            logger.info("notification_outbox_cleanup_started")
            await self.use_case.execute()
            logger.info("notification_outbox_cleanup_completed")
        except Exception:
            logger.exception("notification_outbox_cleanup_failed")
            raise
