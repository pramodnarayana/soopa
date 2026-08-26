import datetime

import structlog
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)

from edi_background_worker.domain.scheduler.handler import JobHandlerPort
from edi_background_worker.domain.scheduler.models import Job

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, use_case: OutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_edi_control_plane_outbox_sweeper_job", job_id=job.id)
        await self.use_case.execute()
        return None
