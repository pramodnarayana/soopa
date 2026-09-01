from datetime import datetime

from scheduler.domain.constants import JobStatus
from scheduler.domain.models import ScheduledJob
from scheduler.ports.outbound.job_repository_port import JobRepositoryPort
from scheduler.ports.outbound.uow_port import SchedulerUnitOfWorkPort


class FakeJobRepository(JobRepositoryPort):
    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}
        self.swept_count = 0

    async def sweep_stuck_jobs(self, lock_lease_ms: int) -> int:
        count = self.swept_count
        self.swept_count = 0
        return count

    async def claim_next_jobs(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[ScheduledJob]:
        claimed = []
        for job in self.jobs.values():
            if job.status == JobStatus.PENDING:
                job_copy = ScheduledJob(
                    id=job.id,
                    name=job.name,
                    target_queue=job.target_queue,
                    payload=job.payload,
                    status=JobStatus.RUNNING,
                    cron_expression=job.cron_expression,
                    interval_seconds=job.interval_seconds,
                    retry_count=job.retry_count,
                    max_retries=job.max_retries,
                    next_run_at=job.next_run_at,
                )
                self.jobs[job.id] = job_copy
                claimed.append(job_copy)
            if len(claimed) >= limit:
                break
        return claimed

    async def reschedule(self, job_id: str, worker_id: str, next_run_at: datetime) -> None:
        if job_id in self.jobs:
            job = self.jobs[job_id]
            self.jobs[job_id] = ScheduledJob(
                id=job.id,
                name=job.name,
                target_queue=job.target_queue,
                payload=job.payload,
                status=JobStatus.PENDING,
                cron_expression=job.cron_expression,
                interval_seconds=job.interval_seconds,
                retry_count=0,
                max_retries=job.max_retries,
                next_run_at=next_run_at,
            )

    async def schedule_retry(
        self, job_id: str, worker_id: str, retry_count: int, next_run_at: datetime
    ) -> None:
        if job_id in self.jobs:
            job = self.jobs[job_id]
            self.jobs[job_id] = ScheduledJob(
                id=job.id,
                name=job.name,
                target_queue=job.target_queue,
                payload=job.payload,
                status=JobStatus.PENDING,
                cron_expression=job.cron_expression,
                interval_seconds=job.interval_seconds,
                retry_count=retry_count,
                max_retries=job.max_retries,
                next_run_at=next_run_at,
            )

    async def mark_completed(self, job_id: str, worker_id: str) -> None:
        if job_id in self.jobs:
            job = self.jobs[job_id]
            self.jobs[job_id] = ScheduledJob(
                id=job.id,
                name=job.name,
                target_queue=job.target_queue,
                payload=job.payload,
                status=JobStatus.COMPLETED,
                cron_expression=job.cron_expression,
                interval_seconds=job.interval_seconds,
                retry_count=job.retry_count,
                max_retries=job.max_retries,
                next_run_at=job.next_run_at,
            )

    async def mark_failed(self, job_id: str, worker_id: str, error_message: str) -> None:
        if job_id in self.jobs:
            job = self.jobs[job_id]
            self.jobs[job_id] = ScheduledJob(
                id=job.id,
                name=job.name,
                target_queue=job.target_queue,
                payload=job.payload,
                status=JobStatus.FAILED,
                cron_expression=job.cron_expression,
                interval_seconds=job.interval_seconds,
                retry_count=job.retry_count,
                max_retries=job.max_retries,
                next_run_at=job.next_run_at,
            )


class FakeSchedulerUow(SchedulerUnitOfWorkPort):
    def __init__(self, repo: FakeJobRepository) -> None:
        self._job_repo = repo
        self.committed = False
        self.rolled_back = False

    @property
    def job_repo(self) -> JobRepositoryPort:
        return self._job_repo

    async def __aenter__(self) -> "FakeSchedulerUow":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
