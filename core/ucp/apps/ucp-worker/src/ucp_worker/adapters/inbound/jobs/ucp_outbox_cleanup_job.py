import datetime

import structlog
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase

from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job

logger = structlog.get_logger(__name__)


class UcpOutboxCleanupJobHandler(JobHandlerPort):
    def __init__(self, use_case: OutboxCleanerUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_ucp_outbox_cleanup_job", job_id=job.id)
        await self.use_case.execute()
        return None
