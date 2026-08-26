import structlog
from outbox.application.sweep_outbox_use_case import (
    SweepOutboxUseCase,
)

logger = structlog.get_logger(__name__)


class NotificationOutboxSweeperJobHandler:
    def __init__(self, use_case: SweepOutboxUseCase):
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("notification_outbox_sweeper_started")
        await self.use_case.execute()
        logger.info("notification_outbox_sweeper_completed")
