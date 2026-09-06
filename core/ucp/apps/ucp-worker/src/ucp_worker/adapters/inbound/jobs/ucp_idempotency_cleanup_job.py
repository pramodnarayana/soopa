import structlog
from ucp.application.use_cases.ucp_idempotency_cleanup_use_case import UcpIdempotencyCleanupUseCase

logger = structlog.get_logger(__name__)


class UcpIdempotencyCleanupJobHandler:
    def __init__(self, use_case: UcpIdempotencyCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_ucp_idempotency_cleanup_job")
        await self.use_case.execute()
