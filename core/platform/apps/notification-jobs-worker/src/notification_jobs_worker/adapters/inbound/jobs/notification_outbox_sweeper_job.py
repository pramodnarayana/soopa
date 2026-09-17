import structlog
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)

logger = structlog.get_logger(__name__)


class NotificationOutboxSweeperJobHandler:
    def __init__(self, use_case: OutboxSweeperUseCase):
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("notification_outbox_sweeper_started")
        await self.use_case.execute()
        logger.info("notification_outbox_sweeper_completed")
