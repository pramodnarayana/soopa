import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import structlog
from croniter import croniter

from scheduler.domain.models import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort
from scheduler.ports.outbound.uow_port import SchedulerUnitOfWorkPort

logger = structlog.get_logger(__name__)


class JobExecutorUseCase:
    def __init__(
        self, uow_factory: Callable[[], SchedulerUnitOfWorkPort], dispatcher: JobDispatcherPort
    ):
        self.uow_factory = uow_factory
        self.dispatcher = dispatcher

    async def execute(self, worker_id: str, limit: int, lock_lease_ms: int) -> None:
        async with self.uow_factory() as uow:
            jobs = await uow.job_repo.claim_next_jobs(
                worker_id=worker_id,
                limit=limit,
                lock_lease_ms=lock_lease_ms,
            )
            # claim_next_jobs modifies rows so it must be committed
            await uow.commit()

        if not jobs:
            return

        logger.info(
            "Worker {worker_id} claimed {count} jobs.",
            worker_id=worker_id,
            count=len(jobs),
        )

        tasks = [self._execute_job(job, worker_id) for job in jobs]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_job(self, job: ScheduledJob, worker_id: str) -> None:
        try:
            if not job.target_queue:
                raise ValueError(f"No target_queue defined for job {job.name}")

            logger.info(
                "Dispatching job {job_name} ({job_id}) to queue {job_target_queue}",
                job_name=job.name,
                job_id=job.id,
                job_target_queue=job.target_queue,
            )

            await self.dispatcher.dispatch(job)

            # Calculate next run if recurring
            if job.cron_expression:
                cron = croniter(job.cron_expression, datetime.now(UTC))
                next_run_at = cron.get_next(datetime)
                async with self.uow_factory() as uow:
                    await uow.job_repo.reschedule(job.id, worker_id, next_run_at)
                    await uow.commit()
                logger.info(
                    "Successfully rescheduled job {job_name} ({job_id}) for {next_run_at} via cron",
                    job_name=job.name,
                    job_id=job.id,
                    next_run_at=next_run_at.isoformat(),
                )
            elif job.interval_seconds is not None and job.interval_seconds > 0:
                next_run_at = datetime.now(UTC) + timedelta(seconds=job.interval_seconds)
                async with self.uow_factory() as uow:
                    await uow.job_repo.reschedule(job.id, worker_id, next_run_at)
                    await uow.commit()
                logger.info(
                    "Successfully rescheduled job {job_name} ({job_id}) for {next_run_at} via interval",
                    job_name=job.name,
                    job_id=job.id,
                    next_run_at=next_run_at.isoformat(),
                )
            else:
                async with self.uow_factory() as uow:
                    await uow.job_repo.mark_completed(job.id, worker_id)
                    await uow.commit()
                logger.info(
                    "Successfully completed job {job_name} ({job_id})",
                    job_name=job.name,
                    job_id=job.id,
                )

        except Exception as e:
            logger.exception("job_execution_failed", job_name=job.name, job_id=job.id)

            if job.retry_count < job.max_retries:
                backoff_seconds = 60 * (2**job.retry_count)
                next_run_at = datetime.fromtimestamp(
                    datetime.now(UTC).timestamp() + backoff_seconds, tz=UTC
                )

                async with self.uow_factory() as uow:
                    await uow.job_repo.schedule_retry(
                        job.id, worker_id, job.retry_count + 1, next_run_at
                    )
                    await uow.commit()
                logger.info(
                    "Scheduled retry for job {job_name} ({job_id}) at {next_run_at}",
                    job_name=job.name,
                    job_id=job.id,
                    next_run_at=next_run_at.isoformat(),
                )
            else:
                async with self.uow_factory() as uow:
                    await uow.job_repo.mark_failed(job.id, worker_id, str(e))
                    await uow.commit()
