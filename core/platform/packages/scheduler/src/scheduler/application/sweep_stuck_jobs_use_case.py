import asyncio

import structlog

from scheduler.ports.job_repository_port import JobRepositoryPort

logger = structlog.get_logger(__name__)


class SweepStuckJobsUseCase:
    def __init__(self, repository: JobRepositoryPort):
        self.repository = repository

    async def execute(self, lock_lease_ms: int) -> int:
        total_swept = 0
        while True:
            swept = await self.repository.sweep_stuck_jobs(lock_lease_ms)
            total_swept += swept
            if swept == 0:
                break
            # Yield execution back to the event loop so postgres can autovacuum
            await asyncio.sleep(0.1)

        if total_swept > 0:
            logger.info("Swept {total_swept} stuck jobs back to PENDING.", total_swept=total_swept)
        return total_swept
