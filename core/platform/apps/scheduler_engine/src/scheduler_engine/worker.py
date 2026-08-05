import asyncio
import logging
import uuid
from datetime import UTC, datetime

from croniter import croniter

from .domain.models import ScheduledJob
from .ports.job_dispatcher import JobDispatcherPort
from .ports.job_repository import JobRepositoryPort

logger = logging.getLogger(__name__)


class SchedulerWorker:
    def __init__(
        self,
        repository: JobRepositoryPort,
        dispatcher: JobDispatcherPort,
        worker_id: str | None = None,
        poll_interval_seconds: int = 5,
        max_concurrent_jobs: int = 10,
        lock_lease_ms: int = 300000,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.worker_id = worker_id or str(uuid.uuid4())
        self.poll_interval_seconds = poll_interval_seconds
        self.max_concurrent_jobs = max_concurrent_jobs
        self.lock_lease_ms = lock_lease_ms
        self.is_running = False

    async def start(self) -> None:
        self.is_running = True
        logger.info(
            f"Starting scheduler worker {self.worker_id} with concurrency {self.max_concurrent_jobs}"
        )
        while self.is_running:
            try:
                await self.poll()
            except Exception:
                logger.exception("Error in scheduler poll loop")
            await asyncio.sleep(self.poll_interval_seconds)

    async def stop(self) -> None:
        self.is_running = False
        logger.info(f"Stopped scheduler worker {self.worker_id}")

    async def poll(self) -> None:
        # 1. Sweep stuck jobs
        swept = await self.repository.sweep_stuck_jobs(self.lock_lease_ms)
        if swept > 0:
            logger.info(f"Swept {swept} stuck jobs back to PENDING.")

        # 2. Claim next jobs using SKIP LOCKED
        jobs = await self.repository.claim_next_jobs(
            worker_id=self.worker_id,
            limit=self.max_concurrent_jobs,
            lock_lease_ms=self.lock_lease_ms,
        )

        if jobs:
            logger.info(f"Worker {self.worker_id} claimed {len(jobs)} jobs.")

            # 3. Execute jobs concurrently
            tasks = [self.execute_job(job) for job in jobs]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def execute_job(self, job: ScheduledJob) -> None:
        try:
            if not job.target_queue:
                raise ValueError(f"No target_queue defined for job {job.name}")

            logger.info(f"Dispatching job {job.name} ({job.id}) to queue {job.target_queue}")

            await self.dispatcher.dispatch(job)

            # Calculate next run if recurring
            if job.cron_expression:
                cron = croniter(job.cron_expression, datetime.now(UTC))
                next_run_at = cron.get_next(datetime)
                await self.repository.reschedule(job.id, self.worker_id, next_run_at)
                logger.info(
                    f"Successfully rescheduled job {job.name} ({job.id}) for {next_run_at.isoformat()}"
                )
            else:
                await self.repository.mark_completed(job.id, self.worker_id)
                logger.info(f"Successfully completed job {job.name} ({job.id})")

        except Exception as e:
            logger.exception("Job %s (%s) execution failed", job.name, job.id)

            if job.retry_count < job.max_retries:
                backoff_seconds = 60 * (2**job.retry_count)
                next_run_at = datetime.fromtimestamp(
                    datetime.now(UTC).timestamp() + backoff_seconds, tz=UTC
                )

                await self.repository.schedule_retry(
                    job.id, self.worker_id, job.retry_count + 1, next_run_at
                )
                logger.info(
                    f"Scheduled retry for job {job.name} ({job.id}) at {next_run_at.isoformat()}"
                )
            else:
                await self.repository.mark_failed(job.id, self.worker_id, str(e))
