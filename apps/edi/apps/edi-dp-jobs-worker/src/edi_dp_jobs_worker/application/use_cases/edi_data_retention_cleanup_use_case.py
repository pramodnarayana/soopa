import structlog

from edi_dp_jobs_worker.ports.outbound.edi_data_retention_cleanup_repository_port import (
    EdiDataRetentionCleanupRepositoryPort,
)

logger = structlog.get_logger(__name__)


import asyncio


class EdiDataRetentionCleanupUseCase:
    """Application UseCase to clean up old EDI Data Plane retention records (ProcessedEvents and TraceEvents)."""

    def __init__(self, repository: EdiDataRetentionCleanupRepositoryPort, retention_days: int = 14):
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        self.repository = repository
        self.retention_days = retention_days

    async def execute(self) -> None:
        logger.info("edi_data_retention_cleanup_started", retention_days=self.retention_days)

        # Execute both sweeps concurrently. If one fails, the other can still succeed.
        results = await asyncio.gather(
            self.repository.cleanup_processed_events(retention_days=self.retention_days),
            self.repository.cleanup_trace_events(retention_days=self.retention_days),
            return_exceptions=True,
        )

        exceptions = [r for r in results if isinstance(r, Exception)]
        if exceptions:
            logger.error(
                "edi_data_retention_cleanup_completed_with_errors", error_count=len(exceptions)
            )
            raise ExceptionGroup("data_retention_cleanup_had_failures", exceptions)

        logger.info("edi_data_retention_cleanup_completed")
