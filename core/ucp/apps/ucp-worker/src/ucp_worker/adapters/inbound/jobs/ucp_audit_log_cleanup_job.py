import structlog
from ucp.application.use_cases.ucp_audit_log_cleanup_use_case import UcpAuditLogCleanupUseCase

logger = structlog.get_logger(__name__)


class UcpAuditLogCleanupJobHandler:
    def __init__(self, use_case: UcpAuditLogCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_ucp_audit_log_cleanup_job")
        await self.use_case.execute()
