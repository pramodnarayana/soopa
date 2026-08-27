import asyncio
from collections.abc import Callable

import structlog

from scheduler.ports.outbound.uow_port import SchedulerUnitOfWorkPort

logger = structlog.get_logger(__name__)


class SweepStuckJobsUseCase:
    def __init__(self, uow_factory: Callable[[], SchedulerUnitOfWorkPort]):
        self.uow_factory = uow_factory

    async def execute(self, lock_lease_ms: int) -> int:
        total_swept = 0
        while True:
            async with self.uow_factory() as uow:
                swept = await uow.job_repo.sweep_stuck_jobs(lock_lease_ms)
                await uow.commit()
            total_swept += swept
            if swept == 0:
                break
            # Yield execution back to the event loop so postgres can autovacuum
            await asyncio.sleep(0.1)

        if total_swept > 0:
            logger.info("Swept {total_swept} stuck jobs back to PENDING.", total_swept=total_swept)
        return total_swept
