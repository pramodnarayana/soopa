import structlog

from edi_background_worker.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)

logger = structlog.get_logger(__name__)


class EdiAuditLogCleanupJobHandler:
    def __init__(self, use_case: EdiAuditLogCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_edi_audit_log_cleanup_job")
        await self.use_case.execute()
