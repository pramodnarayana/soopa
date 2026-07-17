import asyncio
import contextlib
import logging
from typing import Any

from scheduler.ports.publisher import MessagePublisherPort
from scheduler.ports.repository import JobRepositoryPort

logger = logging.getLogger(__name__)


class SchedulerWorkerService:
    def __init__(
        self,
        repository: JobRepositoryPort,
        publisher: MessagePublisherPort,
        worker_id: str,
        max_concurrent_jobs: int = 10,
    ):
        self.repository = repository
        self.publisher = publisher
        self.worker_id = worker_id
        self.max_concurrent_jobs = max_concurrent_jobs
        self._is_running = False
        self._task: asyncio.Task[None] | None = None
        self._active_jobs: set[asyncio.Task[None]] = set()

    async def start(self, poll_interval_seconds: float = 5.0) -> None:
        self._is_running = True
        logger.info(
            f"Starting scheduler worker {self.worker_id} with concurrency {self.max_concurrent_jobs}"
        )
        self._task = asyncio.create_task(self._poll_loop(poll_interval_seconds))

    async def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        if self._active_jobs:
            logger.info(f"Waiting for {len(self._active_jobs)} active jobs to complete...")
            await asyncio.gather(*self._active_jobs, return_exceptions=True)

        logger.info(f"Stopped scheduler worker {self.worker_id}")

    async def _execute_job(self, job: Any) -> None:
        try:
            if not job.target_queue:
                error_msg = f"No target_queue defined for job {job.name}"
                logger.error(error_msg)
                await self.repository.mark_failed(job.id, error=error_msg)
                return

            logger.info(f"Dispatching job {job.name} ({job.id}) to queue {job.target_queue}")
            payload = {
                "job_id": str(job.id),
                "job_name": job.name,
                "payload": job.payload,
            }
            await self.publisher.publish(job.target_queue, payload)

            # Successfully dispatched. Reschedule
            import datetime

            now = datetime.datetime.now(datetime.UTC)
            next_run_at = job.calculate_next_run_at(now)

            if next_run_at:
                await self.repository.reschedule(job.id, next_run_at)
                logger.info(f"Successfully rescheduled job {job.name} ({job.id}) for {next_run_at}")
            else:
                await self.repository.mark_completed(job.id)
                logger.info(f"Successfully completed job {job.name} ({job.id})")

        except Exception as e:
            logger.exception(f"Job {job.name} ({job.id}) dispatch failed: {e}")
            if job.retry_count < job.max_retries:
                import datetime

                backoff_seconds = 60 * (2**job.retry_count)
                next_run_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
                    seconds=backoff_seconds
                )
                await self.repository.schedule_retry(job.id, next_run_at)
                logger.info(f"Scheduled retry for job {job.name} ({job.id}) at {next_run_at}")
            else:
                await self.repository.mark_failed(job.id, error=str(e))

    async def _poll_loop(self, poll_interval_seconds: float) -> None:
        import datetime

        last_sweep = datetime.datetime.now(datetime.UTC)
        while self._is_running:
            try:
                now = datetime.datetime.now(datetime.UTC)
                if (now - last_sweep).total_seconds() > 60:
                    swept = await self.repository.sweep_stuck_jobs(datetime.timedelta(seconds=300))
                    if swept > 0:
                        logger.info(f"Swept {swept} stuck jobs back to PENDING.")
                    last_sweep = now

                # Remove completed tasks from active set
                self._active_jobs = {task for task in self._active_jobs if not task.done()}

                available_slots = self.max_concurrent_jobs - len(self._active_jobs)

                if available_slots > 0:
                    jobs = await self.repository.claim_next_jobs(
                        worker_id=self.worker_id, limit=available_slots
                    )

                    for job in jobs:
                        task = asyncio.create_task(self._execute_job(job))
                        self._active_jobs.add(task)

                    if not jobs:
                        await asyncio.sleep(poll_interval_seconds)
                else:
                    await asyncio.sleep(poll_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler poll loop: {e}")
                await asyncio.sleep(poll_interval_seconds)
