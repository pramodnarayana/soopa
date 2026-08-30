import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from database.provider import get_async_engine
from seedwork import generate_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scheduler.adapters.outbound.database.postgres_job_repository import PostgresJobRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_session() -> "AsyncGenerator[AsyncSession]":
    base_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    engine = get_async_engine(base_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture(autouse=True)
async def clear_scheduling_tables(test_session: AsyncSession) -> None:
    await test_session.execute(
        text("TRUNCATE TABLE scheduling.scheduled_jobs RESTART IDENTITY CASCADE;")
    )
    await test_session.commit()


@pytest.mark.integration
async def test_claim_next_jobs(test_session: AsyncSession) -> None:
    # Insert some jobs manually
    now = datetime.now(UTC)
    job_1_id = generate_id("id")
    job_2_id = generate_id("id")
    future_job_id = generate_id("id")

    await test_session.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs (id, name, status, next_run_at, target_queue, payload, max_retries, retry_count, created_at, updated_at)
            VALUES
            (:job1, 'job1', 'PENDING', :now, 'queue1', '{}'::jsonb, 3, 0, NOW(), NOW()),
            (:job2, 'job2', 'PENDING', :now, 'queue1', '{}'::jsonb, 3, 0, NOW(), NOW()),
            (:job3, 'future_job', 'PENDING', :future, 'queue1', '{}'::jsonb, 3, 0, NOW(), NOW())
        """),
        {
            "job1": job_1_id,
            "job2": job_2_id,
            "job3": future_job_id,
            "now": now,
            "future": now + timedelta(days=1),
        },
    )
    await test_session.commit()

    repo = PostgresJobRepository(test_session)
    jobs = await repo.claim_next_jobs(worker_id="worker-1", limit=10, lock_lease_ms=5000)

    # Should only claim jobs that are PENDING and next_run_at <= NOW()
    assert len(jobs) == 2
    claimed_ids = {job.id for job in jobs}
    assert job_1_id in claimed_ids
    assert job_2_id in claimed_ids
    assert future_job_id not in claimed_ids

    # Verify they were marked as RUNNING in the DB
    result = await test_session.execute(
        text(
            "SELECT status, owner_token, lease_expires_at FROM scheduling.scheduled_jobs WHERE id = :job1"
        ),
        {"job1": job_1_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "RUNNING"
    assert row[1] == "worker-1"
    assert row[2] is not None


@pytest.mark.integration
async def test_reschedule(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    job_id = generate_id("id")

    await test_session.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs (id, name, status, next_run_at, target_queue, owner_token, max_retries, retry_count, payload, created_at, updated_at)
            VALUES (:id, 'job1', 'RUNNING', :now, 'queue1', 'worker-1', 3, 1, '{}'::jsonb, NOW(), NOW())
        """),
        {"id": job_id, "now": now},
    )
    await test_session.commit()

    repo = PostgresJobRepository(test_session)
    next_run = now + timedelta(minutes=10)
    await repo.reschedule(job_id=job_id, worker_id="worker-1", next_run_at=next_run)
    await test_session.commit()

    result = await test_session.execute(
        text(
            "SELECT status, next_run_at, owner_token, retry_count FROM scheduling.scheduled_jobs WHERE id = :id"
        ),
        {"id": job_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "PENDING"
    assert row[1] == next_run
    assert row[2] is None  # owner_token cleared
    assert row[3] == 0  # retry_count reset to 0


@pytest.mark.integration
async def test_schedule_retry(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    job_id = generate_id("id")

    await test_session.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs (id, name, status, next_run_at, target_queue, owner_token, max_retries, retry_count, payload, created_at, updated_at)
            VALUES (:id, 'job1', 'RUNNING', :now, 'queue1', 'worker-1', 3, 0, '{}'::jsonb, NOW(), NOW())
        """),
        {"id": job_id, "now": now},
    )
    await test_session.commit()

    repo = PostgresJobRepository(test_session)
    next_run = now + timedelta(minutes=1)
    await repo.schedule_retry(
        job_id=job_id, worker_id="worker-1", retry_count=1, next_run_at=next_run
    )
    await test_session.commit()

    result = await test_session.execute(
        text(
            "SELECT status, next_run_at, owner_token, retry_count FROM scheduling.scheduled_jobs WHERE id = :id"
        ),
        {"id": job_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "PENDING"
    assert row[1] == next_run
    assert row[2] is None
    assert row[3] == 1


@pytest.mark.integration
async def test_mark_completed(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    job_id = generate_id("id")

    await test_session.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs (id, name, status, next_run_at, target_queue, owner_token, max_retries, retry_count, payload, created_at, updated_at)
            VALUES (:id, 'job1', 'RUNNING', :now, 'queue1', 'worker-1', 3, 0, '{}'::jsonb, NOW(), NOW())
        """),
        {"id": job_id, "now": now},
    )
    await test_session.commit()

    repo = PostgresJobRepository(test_session)
    await repo.mark_completed(job_id=job_id, worker_id="worker-1")
    await test_session.commit()

    result = await test_session.execute(
        text("SELECT status, owner_token FROM scheduling.scheduled_jobs WHERE id = :id"),
        {"id": job_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "COMPLETED"
    assert row[1] is None


@pytest.mark.integration
async def test_mark_failed(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    job_id = generate_id("id")

    await test_session.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs (id, name, status, next_run_at, target_queue, owner_token, max_retries, retry_count, payload, created_at, updated_at)
            VALUES (:id, 'job1', 'RUNNING', :now, 'queue1', 'worker-1', 3, 3, '{}'::jsonb, NOW(), NOW())
        """),
        {"id": job_id, "now": now},
    )
    await test_session.commit()

    repo = PostgresJobRepository(test_session)
    await repo.mark_failed(job_id=job_id, worker_id="worker-1", error_message="fatal error")
    await test_session.commit()

    result = await test_session.execute(
        text(
            "SELECT status, owner_token, error_message FROM scheduling.scheduled_jobs WHERE id = :id"
        ),
        {"id": job_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "FAILED"
    assert row[1] is None
    assert row[2] == "fatal error"


@pytest.mark.integration
async def test_sweep_stuck_jobs(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    stuck_job_id = generate_id("id")
    active_job_id = generate_id("id")

    await test_session.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs (id, name, status, next_run_at, target_queue, owner_token, lease_expires_at, max_retries, retry_count, payload, created_at, updated_at)
            VALUES
            (:stuck, 'job1', 'RUNNING', :now, 'queue1', 'worker-old', :expired_lease, 3, 0, '{}'::jsonb, NOW(), NOW()),
            (:active, 'job2', 'RUNNING', :now, 'queue1', 'worker-new', :active_lease, 3, 0, '{}'::jsonb, NOW(), NOW())
        """),
        {
            "stuck": stuck_job_id,
            "active": active_job_id,
            "now": now,
            "expired_lease": now - timedelta(minutes=5),
            "active_lease": now + timedelta(minutes=5),
        },
    )
    await test_session.commit()

    repo = PostgresJobRepository(test_session)
    swept_count = await repo.sweep_stuck_jobs(lock_lease_ms=5000)
    await test_session.commit()

    assert swept_count == 1

    # Verify stuck job was reset to PENDING
    result = await test_session.execute(
        text("SELECT status FROM scheduling.scheduled_jobs WHERE id = :id"), {"id": stuck_job_id}
    )
    assert result.fetchone()[0] == "PENDING"

    # Verify active job is still RUNNING
    result = await test_session.execute(
        text("SELECT status FROM scheduling.scheduled_jobs WHERE id = :id"), {"id": active_job_id}
    )
    assert result.fetchone()[0] == "RUNNING"
