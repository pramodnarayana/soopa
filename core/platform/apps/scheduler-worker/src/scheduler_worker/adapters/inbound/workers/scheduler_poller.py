import asyncio

import structlog
from scheduler.application.job_executor_use_case import JobExecutorUseCase
from scheduler.application.job_sweeper_use_case import JobSweeperUseCase
from seedwork import SystemIdPrefix, generate_id

logger = structlog.get_logger(__name__)


class SchedulerPoller:
    def __init__(
        self,
        sweep_use_case: JobSweeperUseCase,
        claim_use_case: JobExecutorUseCase,
        worker_id: str | None = None,
        poll_interval_seconds: int = 5,
        max_concurrent_jobs: int = 10,
        lock_lease_ms: int = 300000,
    ):
        self.sweep_use_case = sweep_use_case
        self.claim_use_case = claim_use_case
        self.worker_id = worker_id or generate_id(SystemIdPrefix.GENERIC)
        self.poll_interval_seconds = poll_interval_seconds
        self.max_concurrent_jobs = max_concurrent_jobs
        self.lock_lease_ms = lock_lease_ms
        self.is_running = False

    async def start(self) -> None:
        self.is_running = True
        logger.info(
            "Starting scheduler worker {worker_id} with concurrency {max_concurrent_jobs}",
            worker_id=self.worker_id,
            max_concurrent_jobs=self.max_concurrent_jobs,
        )
        while self.is_running:
            try:
                await self.poll()
            except Exception:
                logger.exception("Error in scheduler poll loop")
            await asyncio.sleep(self.poll_interval_seconds)

    async def stop(self) -> None:
        self.is_running = False
        logger.info("Stopped scheduler worker {worker_id}", worker_id=self.worker_id)

    async def poll(self) -> None:
        # 1. Sweep stuck jobs
        await self.sweep_use_case.execute(lock_lease_ms=self.lock_lease_ms)

        # 2. Claim and execute jobs
        await self.claim_use_case.execute(
            worker_id=self.worker_id,
            limit=self.max_concurrent_jobs,
            lock_lease_ms=self.lock_lease_ms,
        )
