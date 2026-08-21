import datetime

import structlog
from ucp.application.use_cases.ucp_idempotency_cleanup_use_case import UcpIdempotencyCleanupUseCase

from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job

logger = structlog.get_logger(__name__)


class UcpIdempotencyCleanupJobHandler(JobHandlerPort):
    def __init__(self, use_case: UcpIdempotencyCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_ucp_idempotency_cleanup_job", job_id=job.id)
        await self.use_case.execute()
        return None
