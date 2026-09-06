import structlog
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxSweeperJobHandler:
    def __init__(self, use_case: OutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_edi_control_plane_outbox_sweeper_job")
        await self.use_case.execute()
