from datetime import UTC, datetime, timedelta

from database.models.scheduling import ScheduledJob as OrmScheduledJob
from sqlalchemy import ScalarSelect, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob
from scheduler.ports.outbound.job_repository_port import JobRepositoryPort

_MAX_UTC = datetime.max.replace(tzinfo=UTC)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SqlAlchemyJobRepository(JobRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_domain_model(record: OrmScheduledJob) -> ScheduledJob:
        return ScheduledJob(
            id=record.id,
            name=record.name,
            target_queue=record.target_queue,
            payload=dict(record.payload) if record.payload else {},
            status=JobStatus(record.status),
            cron_expression=record.cron_expression,
            interval_seconds=record.interval_seconds,
            retry_count=record.retry_count,
            max_retries=record.max_retries,
            next_run_at=record.next_run_at,
        )

    async def sweep_stuck_jobs(self, lock_lease_ms: int) -> int:
        now_naive_utc = datetime.now(UTC).replace(tzinfo=None)
        stale_cutoff_naive_utc = now_naive_utc - timedelta(milliseconds=lock_lease_ms)
        stuck_ids_subq = (
            select(OrmScheduledJob.id)
            .where(
                OrmScheduledJob.status == JobStatus.RUNNING.value,
                or_(
                    OrmScheduledJob.lease_expires_at <= func.now(),
                    and_(
                        OrmScheduledJob.lease_expires_at.is_(None),
                        OrmScheduledJob.updated_at <= stale_cutoff_naive_utc,
                    ),
                ),
            )
            .limit(100)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(OrmScheduledJob)
            .where(OrmScheduledJob.id.in_(stuck_ids_subq))
            .values(
                status=JobStatus.PENDING.value,
                lease_expires_at=None,
                owner_token=None,
                updated_at=now_naive_utc,
            )
            .returning(OrmScheduledJob.id)
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    @staticmethod
    def _build_claimable_ids_subquery(limit: int) -> ScalarSelect[str]:
        return (
            select(OrmScheduledJob.id)
            .where(
                or_(
                    OrmScheduledJob.status == JobStatus.PENDING.value,
                    and_(
                        OrmScheduledJob.status == JobStatus.RUNNING.value,
                        OrmScheduledJob.lease_expires_at < func.now(),
                    ),
                ),
                or_(
                    OrmScheduledJob.next_run_at.is_(None),
                    OrmScheduledJob.next_run_at <= func.now(),
                ),
            )
            .order_by(OrmScheduledJob.next_run_at.asc().nulls_last(), OrmScheduledJob.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )

    @staticmethod
    def _sort_claimed_jobs(jobs: list[ScheduledJob]) -> list[ScheduledJob]:
        return sorted(
            jobs,
            key=lambda job: (
                job.next_run_at is None,
                _normalize_utc(job.next_run_at) if job.next_run_at is not None else _MAX_UTC,
                job.id,
            ),
        )

    async def claim_next_jobs(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[ScheduledJob]:
        now_naive_utc = datetime.now(UTC).replace(tzinfo=None)
        claimable_ids_subq = self._build_claimable_ids_subquery(limit)
        stmt = (
            update(OrmScheduledJob)
            .where(OrmScheduledJob.id.in_(claimable_ids_subq))
            .values(
                status=JobStatus.RUNNING.value,
                lease_expires_at=func.now() + timedelta(milliseconds=lock_lease_ms),
                owner_token=worker_id,
                updated_at=now_naive_utc,
            )
            .returning(OrmScheduledJob)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return self._sort_claimed_jobs([self._to_domain_model(record) for record in records])

    async def reschedule(self, job_id: str, worker_id: str, next_run_at: datetime) -> None:
        stmt = (
            update(OrmScheduledJob)
            .where(
                OrmScheduledJob.id == job_id,
                OrmScheduledJob.status == JobStatus.RUNNING.value,
                OrmScheduledJob.owner_token == worker_id,
            )
            .values(
                status=JobStatus.PENDING.value,
                lease_expires_at=None,
                owner_token=None,
                retry_count=0,
                next_run_at=next_run_at,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await self.session.execute(stmt)

    async def schedule_retry(
        self, job_id: str, worker_id: str, retry_count: int, next_run_at: datetime
    ) -> None:
        stmt = (
            update(OrmScheduledJob)
            .where(
                OrmScheduledJob.id == job_id,
                OrmScheduledJob.status == JobStatus.RUNNING.value,
                OrmScheduledJob.owner_token == worker_id,
            )
            .values(
                status=JobStatus.PENDING.value,
                lease_expires_at=None,
                owner_token=None,
                retry_count=retry_count,
                next_run_at=next_run_at,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await self.session.execute(stmt)

    async def mark_completed(self, job_id: str, worker_id: str) -> None:
        stmt = (
            update(OrmScheduledJob)
            .where(
                OrmScheduledJob.id == job_id,
                OrmScheduledJob.status == JobStatus.RUNNING.value,
                OrmScheduledJob.owner_token == worker_id,
            )
            .values(
                status=JobStatus.COMPLETED.value,
                lease_expires_at=None,
                owner_token=None,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await self.session.execute(stmt)

    async def mark_failed(self, job_id: str, worker_id: str, error_message: str) -> None:
        stmt = (
            update(OrmScheduledJob)
            .where(
                OrmScheduledJob.id == job_id,
                OrmScheduledJob.status == JobStatus.RUNNING.value,
                OrmScheduledJob.owner_token == worker_id,
            )
            .values(
                status=JobStatus.FAILED.value,
                lease_expires_at=None,
                owner_token=None,
                error_message=error_message,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await self.session.execute(stmt)
