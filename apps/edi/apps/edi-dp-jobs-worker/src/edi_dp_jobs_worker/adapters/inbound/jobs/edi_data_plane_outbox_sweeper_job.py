import structlog

from edi_dp_jobs_worker.application.use_cases.edi_data_plane_outbox_sweeper_use_case import (
    EdiDataPlaneOutboxSweeperUseCase,
)

logger = structlog.get_logger(__name__)


class EdiDataPlaneOutboxSweeperJobHandler:
    def __init__(self, use_case: EdiDataPlaneOutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_edi_data_plane_outbox_sweeper_job")
        await self.use_case.execute()
