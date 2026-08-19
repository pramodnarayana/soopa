import structlog

from notification.application.sweep_outbox_use_case import SweepNotificationOutboxUseCase

logger = structlog.get_logger(__name__)


class NotificationOutboxSweeperJobHandler:
    def __init__(self, use_case: SweepNotificationOutboxUseCase):
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("Handling Notification Outbox Sweeper Job")
        await self.use_case.execute()
