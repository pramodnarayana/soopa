import datetime

import structlog
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)

from edi_background_worker.domain.scheduler.handler import JobHandlerPort
from edi_background_worker.domain.scheduler.models import Job

logger = structlog.get_logger(__name__)


class EdiDataPlaneOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, use_case: OutboxSweeperUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        """
        Sweeps the data-plane (tenant shard) outbox for PENDING pipeline events
        and forwards each one to the appropriate SQS queue using concurrent batching.
        """
        logger.info("[EdiDataPlaneOutboxSweeperJobHandler] Triggering sweep for job", job_id=job.id)

        await self.use_case.execute()

        interval_seconds = (
            job.interval_seconds if job.interval_seconds and job.interval_seconds > 0 else 60
        )
        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=interval_seconds)
