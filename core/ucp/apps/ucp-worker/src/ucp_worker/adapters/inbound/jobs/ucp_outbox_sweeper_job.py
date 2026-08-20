import datetime

import structlog
from ucp.application.sweep_outbox_use_case import SweepControlPlaneOutboxUseCase

from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job

logger = structlog.get_logger(__name__)


class UcpOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, use_case: SweepControlPlaneOutboxUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_ucp_outbox_sweeper_job", job_id=job.id)

        await self.use_case.execute()

        # Return None to rely on the cron schedule interval defined in the scheduler
        return None
