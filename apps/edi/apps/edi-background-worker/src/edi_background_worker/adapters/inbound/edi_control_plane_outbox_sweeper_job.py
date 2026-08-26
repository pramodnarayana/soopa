import datetime

import structlog

from edi_background_worker.application.use_cases.edi_control_plane_outbox_sweeper_use_case import (
    EdiControlPlaneOutboxSweeperUseCase,
)
from edi_background_worker.domain.scheduler.handler import JobHandlerPort
from edi_background_worker.domain.scheduler.models import Job

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, use_case: EdiControlPlaneOutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info(
            "[EdiControlPlaneOutboxSweeperJobHandler] Triggering sweep for job {job.id}",
            job_id=job.id,
        )

        await self.use_case.execute()

        interval_seconds = (
            job.interval_seconds if job.interval_seconds and job.interval_seconds > 0 else 60
        )
        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=interval_seconds)
