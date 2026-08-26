import datetime

import structlog
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase

from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job

logger = structlog.get_logger(__name__)


class UcpOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, use_case: OutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_ucp_outbox_sweeper_job", job_id=job.id)

        await self.use_case.execute()

        # Return None to rely on the cron schedule interval defined in the scheduler
        return None
