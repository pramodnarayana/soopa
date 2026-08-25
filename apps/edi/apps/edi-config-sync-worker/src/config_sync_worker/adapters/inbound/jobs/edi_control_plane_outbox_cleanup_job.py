import datetime

import structlog

from config_sync_worker.application.use_cases.edi_control_plane_outbox_cleanup_use_case import (
    EdiControlPlaneOutboxCleanupUseCase,
)
from config_sync_worker.domain.scheduler.handler import JobHandlerPort
from config_sync_worker.domain.scheduler.models import Job

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxCleanupJobHandler(JobHandlerPort):
    def __init__(self, use_case: EdiControlPlaneOutboxCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_edi_control_plane_outbox_cleanup_job", job_id=job.id)
        await self.use_case.execute()
        return None
