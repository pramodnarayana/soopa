import structlog

from edi_background_worker.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)

logger = structlog.get_logger(__name__)


class EdiIdempotencyCleanupJobHandler:
    def __init__(self, use_case: EdiIdempotencyCleanupUseCase) -> None:
        self.use_case = use_case

    async def execute(self) -> None:
        logger.info("handling_edi_idempotency_cleanup_job")
        await self.use_case.execute()
