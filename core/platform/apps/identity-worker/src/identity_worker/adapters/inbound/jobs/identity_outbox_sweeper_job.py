import structlog
from outbox.application.sweep_outbox_use_case import SweepOutboxUseCase

logger = structlog.get_logger(__name__)


class IdentityOutboxSweeperJobHandler:
    """
    Background job that sweeps stuck outbox events back to PENDING and publishes them.
    Events can become stuck in PROCESSING if the worker crashes before marking them COMPLETED.
    """

    def __init__(self, use_case: SweepOutboxUseCase):
        self.use_case = use_case

    async def execute(self) -> None:
        try:
            logger.info("identity_outbox_sweeper_started")
            await self.use_case.execute()
            logger.info("identity_outbox_sweeper_completed")
        except Exception:
            logger.exception("identity_outbox_sweeper_failed")
