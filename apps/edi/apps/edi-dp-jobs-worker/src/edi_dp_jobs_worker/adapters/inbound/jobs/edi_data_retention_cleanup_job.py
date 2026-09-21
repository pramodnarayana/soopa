import structlog

from edi_dp_jobs_worker.application.use_cases.edi_data_retention_cleanup_use_case import (
    EdiDataRetentionCleanupUseCase,
)

logger = structlog.get_logger(__name__)


class EdiDataRetentionCleanupJobHandler:
    def __init__(self, use_case: EdiDataRetentionCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_edi_data_retention_cleanup_job")
        await self.use_case.execute()
