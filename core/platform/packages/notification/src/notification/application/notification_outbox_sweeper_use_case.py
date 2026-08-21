import structlog

from ..ports.outbound.notification_outbox_repository_port import NotificationOutboxRepositoryPort

logger = structlog.get_logger(__name__)


class NotificationOutboxSweeperUseCase:
    def __init__(
        self,
        repository: NotificationOutboxRepositoryPort,
        lock_lease_ms: int = 30000,
    ):
        self.repository = repository
        self.lock_lease_ms = lock_lease_ms

    async def execute(self) -> None:
        logger.info("Executing Notification Outbox Fallback Sweep Use Case")
        try:
            # Sweep stuck messages back to PENDING so the Relay can pick them up
            swept = await self.repository.sweep_stuck_messages(self.lock_lease_ms)
            if swept > 0:
                logger.info("Swept {swept} stuck notification outbox messages.", swept=swept)
            else:
                logger.debug("No stuck notification messages found.")
        except Exception:
            logger.exception("Error during Notification outbox fallback sweep")
            raise
