import datetime

import structlog
from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job

from worker.application.edi_audit_log_cleanup_use_case import EdiAuditLogCleanupUseCase

logger = structlog.get_logger(__name__)


class EdiAuditLogCleanupJobHandler(JobHandlerPort):
    def __init__(self, use_case: EdiAuditLogCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self, job: Job) -> datetime.datetime | None:
        logger.info("handling_edi_audit_log_cleanup_job", job_id=job.id)
        await self.use_case.execute()
        return None
