import asyncio
import contextlib
import logging

from scheduler.ports.handler import JobHandlerPort
from scheduler.ports.repository import JobRepositoryPort

logger = logging.getLogger(__name__)


class SchedulerWorkerService:
    def __init__(self, repository: JobRepositoryPort, worker_id: str):
        self.repository = repository
        self.worker_id = worker_id
        self.handlers: dict[str, JobHandlerPort] = {}
        self._is_running = False
        self._task: asyncio.Task[None] | None = None

    def register_handler(self, job_name: str, handler: JobHandlerPort) -> None:
        self.handlers[job_name] = handler

    async def start(self, poll_interval_seconds: float = 5.0) -> None:
        self._is_running = True
        logger.info(f"Starting scheduler worker {self.worker_id}")
        self._task = asyncio.create_task(self._poll_loop(poll_interval_seconds))

    async def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info(f"Stopped scheduler worker {self.worker_id}")

    async def _poll_loop(self, poll_interval_seconds: float) -> None:
        while self._is_running:
            try:
                job = await self.repository.claim_next_job(worker_id=self.worker_id)
                if job:
                    handler = self.handlers.get(job.name)
                    if not handler:
                        error_msg = f"No handler registered for job {job.name}"
                        logger.error(error_msg)
                        await self.repository.mark_failed(job.id, error=error_msg)
                        continue

                    try:
                        logger.info(f"Executing job {job.name} ({job.id})")
                        next_run_at = await handler.execute(job)
                        if next_run_at:
                            await self.repository.reschedule(job.id, next_run_at)
                            logger.info(
                                f"Successfully rescheduled job {job.name} ({job.id}) for {next_run_at}"
                            )
                        else:
                            await self.repository.mark_completed(job.id)
                            logger.info(f"Successfully completed job {job.name} ({job.id})")
                    except Exception as e:
                        logger.exception(f"Job {job.name} ({job.id}) failed: {e}")
                        await self.repository.mark_failed(job.id, error=str(e))
                else:
                    await asyncio.sleep(poll_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler poll loop: {e}")
                await asyncio.sleep(poll_interval_seconds)
