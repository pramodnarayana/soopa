import datetime

import structlog
from worker.domain.scheduler.handler import JobHandlerPort
from worker.domain.scheduler.models import Job

from worker.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)

logger = structlog.get_logger(__name__)


class EdiIdempotencyCleanupJobHandler(JobHandlerPort):
    def __init__(self, use_case: EdiIdempotencyCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_edi_idempotency_cleanup_job", job_id=job.id)
        await self.use_case.execute()
        return None
