import structlog
from notification.application.notification_outbox_sweeper_use_case import (
    NotificationOutboxSweeperUseCase,
)

logger = structlog.get_logger(__name__)


class NotificationOutboxSweeperJob:
    def __init__(self, use_case: NotificationOutboxSweeperUseCase):
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("Handling Notification Outbox Cleanup Job")
        await self.use_case.execute()
