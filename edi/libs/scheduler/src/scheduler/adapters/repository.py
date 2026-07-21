import datetime
import logging
import uuid
from typing import Any

from database.models.scheduled_job import ScheduledJob
from scheduler.domain.models import Job, JobStatus
from scheduler.ports.repository import JobRepositoryPort
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

logger = logging.getLogger(__name__)


class SqlAlchemyJobRepository(JobRepositoryPort):
    def __init__(self, engine: AsyncEngine, lock_lease_seconds: int = 300):
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self.lock_lease_seconds = lock_lease_seconds

    def _to_domain(self, record: ScheduledJob) -> Job:
        return Job(
            id=record.id,
            name=record.name,
            payload=record.payload,
            status=JobStatus(record.status),
            next_run_at=record.next_run_at,
            target_queue=record.target_queue,
            app_namespace=record.app_namespace,
            cron_expression=record.cron_expression,
            timezone=record.timezone,
            interval_seconds=record.interval_seconds,
            retry_count=record.retry_count,
            max_retries=record.max_retries,
            locked_at=record.locked_at,
            locked_by=record.locked_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def claim_next_jobs(self, worker_id: str, limit: int) -> list[Job]:
        """
        Uses SKIP LOCKED to safely claim the next PENDING or ready jobs.
        """
        now = datetime.datetime.now(datetime.UTC)

        async with self.session_factory() as session, session.begin():
            # Find the next
            stmt = (
                select(ScheduledJob)
                .where(
                    (
                        (ScheduledJob.status == JobStatus.PENDING.value)
                        | (
                            (ScheduledJob.status == JobStatus.RUNNING.value)
                            & (
                                ScheduledJob.locked_at
                                < now - datetime.timedelta(seconds=self.lock_lease_seconds)
                            )
                        )
                    )
                    & (ScheduledJob.next_run_at.is_(None) | (ScheduledJob.next_run_at <= now))
                )
                .order_by(
                    ScheduledJob.next_run_at.asc().nulls_first(), ScheduledJob.created_at.asc()
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

            if not records:
                return []

            claimed = []
            for record in records:
                record.status = JobStatus.RUNNING.value
                record.locked_at = now
                record.locked_by = worker_id
                claimed.append(self._to_domain(record))

            await session.flush()
            return claimed

    async def sweep_stuck_jobs(self, timeout: datetime.timedelta) -> int:
        now = datetime.datetime.now(datetime.UTC)
        threshold = now - timeout
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(ScheduledJob)
                .where(
                    (ScheduledJob.status == JobStatus.RUNNING.value)
                    & (ScheduledJob.locked_at < threshold)
                )
                .values(
                    status=JobStatus.PENDING.value,
                    locked_at=None,
                    locked_by=None,
                )
            )
            result = await session.execute(stmt)
            return int(result.rowcount) if result.rowcount is not None else 0  # type: ignore[attr-defined]

    async def mark_completed(self, job_id: uuid.UUID) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(
                    status=JobStatus.COMPLETED.value,
                    locked_at=None,
                    locked_by=None,
                )
            )
            await session.execute(stmt)

    async def mark_failed(self, job_id: uuid.UUID, error: str) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(
                    status=JobStatus.FAILED.value,
                    locked_at=None,
                    locked_by=None,
                    error_message=error,
                )
            )
            await session.execute(stmt)

    async def schedule_job(
        self,
        name: str,
        payload: dict[str, Any],
        next_run_at: datetime.datetime | None = None,
        interval_seconds: int | None = None,
    ) -> Job:
        async with self.session_factory() as session, session.begin():
            record = ScheduledJob(
                name=name,
                payload=payload,
                status=JobStatus.PENDING.value,
                next_run_at=next_run_at,
                interval_seconds=interval_seconds,
            )
            session.add(record)
            await session.flush()
            return self._to_domain(record)

    async def reschedule(self, job_id: uuid.UUID, next_run_at: datetime.datetime) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(
                    status=JobStatus.PENDING.value,
                    next_run_at=next_run_at,
                    locked_at=None,
                    locked_by=None,
                    retry_count=0,
                )
            )
            await session.execute(stmt)

    async def schedule_retry(self, job_id: uuid.UUID, next_run_at: datetime.datetime) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id)
                .values(
                    status=JobStatus.PENDING.value,
                    next_run_at=next_run_at,
                    locked_at=None,
                    locked_by=None,
                    retry_count=ScheduledJob.retry_count + 1,
                )
            )
            await session.execute(stmt)
