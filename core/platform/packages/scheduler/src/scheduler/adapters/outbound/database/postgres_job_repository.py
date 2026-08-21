from datetime import datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scheduler.domain.models import ScheduledJob
from scheduler.ports.outbound.job_repository_port import JobRepositoryPort


class PostgresJobRepository(JobRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def sweep_stuck_jobs(self, lock_lease_ms: int) -> int:
        async with self.session_factory() as session:
            query = text("""
                WITH stuck_jobs AS (
                    SELECT id FROM scheduling.job
                    WHERE status = 'RUNNING' AND lease_expires_at <= NOW()
                    LIMIT 100
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE scheduling.job j
                SET status = 'PENDING', lease_expires_at = NULL, owner_token = NULL
                FROM stuck_jobs
                WHERE j.id = stuck_jobs.id
            """)
            result = await session.execute(query)
            await session.commit()
            return cast(CursorResult[Any], result).rowcount

    async def claim_next_jobs(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[ScheduledJob]:
        async with self.session_factory() as session:
            query = text("""
                UPDATE scheduling.job
                SET status = 'RUNNING', lease_expires_at = NOW() + interval '1 millisecond' * :lock_lease_ms, owner_token = :worker_id
                WHERE id IN (
                    SELECT id FROM scheduling.job
                    WHERE (status = 'PENDING' OR (status = 'RUNNING' AND lease_expires_at < NOW()))
                      AND next_run_at <= NOW()
                    ORDER BY next_run_at ASC, id ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *;
            """)
            result = await session.execute(
                query,
                {
                    "worker_id": worker_id,
                    "lock_lease_ms": lock_lease_ms,
                    "limit": limit,
                },
            )
            await session.commit()

            jobs = []
            for row in result:
                mapping = row._mapping
                jobs.append(
                    ScheduledJob(
                        id=mapping["id"],
                        name=mapping["name"],
                        target_queue=mapping.get("target_queue"),
                        payload=mapping.get("payload", {}),
                        status=mapping["status"],
                        cron_expression=mapping.get("cron_expression"),
                        interval_seconds=mapping.get("interval_seconds"),
                        retry_count=mapping.get("retry_count", 0),
                        max_retries=mapping.get("max_retries", 3),
                        next_run_at=mapping.get("next_run_at"),
                    )
                )
            return jobs

    async def reschedule(self, job_id: str, worker_id: str, next_run_at: datetime) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE scheduling.job
                SET status = 'PENDING', lease_expires_at = NULL, owner_token = NULL, retry_count = 0, next_run_at = :next_run_at
                WHERE id = :job_id AND status = 'RUNNING' AND owner_token = :worker_id
            """)
            await session.execute(
                query,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "next_run_at": next_run_at,
                },
            )
            await session.commit()

    async def schedule_retry(
        self, job_id: str, worker_id: str, retry_count: int, next_run_at: datetime
    ) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE scheduling.job
                SET status = 'PENDING', lease_expires_at = NULL, owner_token = NULL, retry_count = :retry_count, next_run_at = :next_run_at
                WHERE id = :job_id AND status = 'RUNNING' AND owner_token = :worker_id
            """)
            await session.execute(
                query,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "retry_count": retry_count,
                    "next_run_at": next_run_at,
                },
            )
            await session.commit()

    async def mark_completed(self, job_id: str, worker_id: str) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE scheduling.job
                SET status = 'COMPLETED', lease_expires_at = NULL, owner_token = NULL
                WHERE id = :job_id AND status = 'RUNNING' AND owner_token = :worker_id
            """)
            await session.execute(
                query,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                },
            )
            await session.commit()

    async def mark_failed(self, job_id: str, worker_id: str, error_message: str) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE scheduling.job
                SET status = 'FAILED', lease_expires_at = NULL, owner_token = NULL, error_message = :error_message
                WHERE id = :job_id AND status = 'RUNNING' AND owner_token = :worker_id
            """)
            await session.execute(
                query,
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "error_message": error_message,
                },
            )
            await session.commit()
