import structlog
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)

logger = structlog.get_logger(__name__)


class EdiDataPlaneOutboxSweeperJobHandler:
    def __init__(self, use_case: OutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        """
        Sweeps the data-plane (tenant shard) outbox for PENDING pipeline events
        and forwards each one to the appropriate SQS queue using concurrent batching.
        """
        logger.info("handling_edi_data_plane_outbox_sweeper_job")
        await self.use_case.execute()
