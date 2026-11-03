from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from database.models.scheduling import ScheduledJob as OrmScheduledJob
from database.provider import get_async_engine
from seedwork import generate_id
from seedwork.id_registry import SystemIdPrefix
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from scheduler.adapters.outbound.database.sqlalchemy_job_repository import SqlAlchemyJobRepository
from scheduler.domain.constants import JobStatus

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db_connection() -> AsyncGenerator[AsyncConnection]:
    base_url = os.environ["DATABASE_URL"]
    engine = get_async_engine(base_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(db_connection: AsyncConnection) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with factory() as session:
        await session.execute(delete(OrmScheduledJob))
        await session.flush()
        yield session


@pytest.mark.integration
async def test_claim_next_jobs(test_session: AsyncSession) -> None:
    now = datetime.now(UTC) - timedelta(seconds=10)
    null_job_id = generate_id(SystemIdPrefix.JOB.value)
    job_1_id = generate_id(SystemIdPrefix.JOB.value)
    job_2_id = generate_id(SystemIdPrefix.JOB.value)
    future_job_id = generate_id(SystemIdPrefix.JOB.value)

    test_session.add_all(
        [
            OrmScheduledJob(
                id=null_job_id,
                name=f"null_job_{null_job_id}",
                status=JobStatus.PENDING.value,
                next_run_at=None,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                payload={"batch": 0},
                max_retries=3,
                retry_count=0,
            ),
            OrmScheduledJob(
                id=job_1_id,
                name=f"job1_{job_1_id}",
                status=JobStatus.PENDING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                payload={"batch": 1},
                max_retries=3,
                retry_count=0,
            ),
            OrmScheduledJob(
                id=job_2_id,
                name=f"job2_{job_2_id}",
                status=JobStatus.PENDING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                payload={"batch": 2},
                max_retries=3,
                retry_count=0,
            ),
            OrmScheduledJob(
                id=future_job_id,
                name=f"future_{future_job_id}",
                status=JobStatus.PENDING.value,
                next_run_at=now + timedelta(days=1),
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                payload={},
                max_retries=3,
                retry_count=0,
            ),
        ]
    )
    await test_session.flush()

    repo = SqlAlchemyJobRepository(test_session)
    jobs = await repo.claim_next_jobs(worker_id="worker-1", limit=10, lock_lease_ms=5000)

    assert len(jobs) == 3
    assert {jobs[0].id, jobs[1].id} == {job_1_id, job_2_id}
    assert jobs[-1].id == null_job_id
    claimed_ids = {job.id for job in jobs}
    assert claimed_ids == {null_job_id, job_1_id, job_2_id}

    persisted = (
        await test_session.execute(select(OrmScheduledJob).where(OrmScheduledJob.id == job_1_id))
    ).scalar_one()
    assert persisted.status == JobStatus.RUNNING.value
    assert persisted.owner_token == "worker-1"
    assert persisted.lease_expires_at is not None


@pytest.mark.integration
async def test_reschedule_and_optimistic_lock_fence(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    job_id = generate_id(SystemIdPrefix.JOB.value)

    test_session.add(
        OrmScheduledJob(
            id=job_id,
            name=f"resched_{job_id}",
            status=JobStatus.RUNNING.value,
            next_run_at=now,
            target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
            owner_token="worker-1",
            max_retries=3,
            retry_count=1,
            payload={},
        )
    )
    await test_session.flush()

    repo = SqlAlchemyJobRepository(test_session)
    next_run = now + timedelta(minutes=10)

    # Stale worker must not mutate a job owned by worker-1
    await repo.reschedule(job_id=job_id, worker_id="stale-worker", next_run_at=next_run)
    await test_session.flush()
    still_running = await test_session.get(OrmScheduledJob, job_id)
    assert still_running is not None
    assert still_running.status == JobStatus.RUNNING.value

    # Active owner reschedules cleanly
    await repo.reschedule(job_id=job_id, worker_id="worker-1", next_run_at=next_run)
    await test_session.flush()
    await test_session.refresh(still_running)
    assert still_running.status == JobStatus.PENDING.value
    assert still_running.next_run_at == next_run
    assert still_running.owner_token is None
    assert still_running.retry_count == 0


@pytest.mark.integration
async def test_schedule_retry(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    job_id = generate_id(SystemIdPrefix.JOB.value)

    test_session.add(
        OrmScheduledJob(
            id=job_id,
            name=f"retry_{job_id}",
            status=JobStatus.RUNNING.value,
            next_run_at=now,
            target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
            owner_token="worker-1",
            max_retries=3,
            retry_count=0,
            payload={},
        )
    )
    await test_session.flush()

    repo = SqlAlchemyJobRepository(test_session)
    next_run = now + timedelta(minutes=1)
    await repo.schedule_retry(
        job_id=job_id, worker_id="worker-1", retry_count=1, next_run_at=next_run
    )
    await test_session.flush()

    row = await test_session.get(OrmScheduledJob, job_id)
    assert row is not None
    await test_session.refresh(row)
    assert row.status == JobStatus.PENDING.value
    assert row.next_run_at == next_run
    assert row.owner_token is None
    assert row.retry_count == 1


@pytest.mark.integration
async def test_mark_completed_and_mark_failed(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    completed_id = generate_id(SystemIdPrefix.JOB.value)
    failed_id = generate_id(SystemIdPrefix.JOB.value)

    test_session.add_all(
        [
            OrmScheduledJob(
                id=completed_id,
                name=f"complete_{completed_id}",
                status=JobStatus.RUNNING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                owner_token="worker-1",
                max_retries=3,
                retry_count=0,
                payload={},
            ),
            OrmScheduledJob(
                id=failed_id,
                name=f"fail_{failed_id}",
                status=JobStatus.RUNNING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                owner_token="worker-1",
                max_retries=3,
                retry_count=3,
                payload={},
            ),
        ]
    )
    await test_session.flush()

    repo = SqlAlchemyJobRepository(test_session)
    await repo.mark_completed(job_id=completed_id, worker_id="worker-1")
    await repo.mark_failed(job_id=failed_id, worker_id="worker-1", error_message="fatal error")
    await test_session.flush()

    completed_row = await test_session.get(OrmScheduledJob, completed_id)
    failed_row = await test_session.get(OrmScheduledJob, failed_id)
    assert completed_row is not None
    assert failed_row is not None
    await test_session.refresh(completed_row)
    await test_session.refresh(failed_row)

    assert completed_row.status == JobStatus.COMPLETED.value
    assert completed_row.owner_token is None
    assert failed_row.status == JobStatus.FAILED.value
    assert failed_row.owner_token is None
    assert failed_row.error_message == "fatal error"


@pytest.mark.integration
async def test_sweep_stuck_jobs_handles_expired_and_null_lease(test_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    expired_lease_id = generate_id(SystemIdPrefix.JOB.value)
    null_lease_stale_id = generate_id(SystemIdPrefix.JOB.value)
    active_job_id = generate_id(SystemIdPrefix.JOB.value)

    test_session.add_all(
        [
            OrmScheduledJob(
                id=expired_lease_id,
                name=f"expired_{expired_lease_id}",
                status=JobStatus.RUNNING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                owner_token="worker-old",
                lease_expires_at=now - timedelta(minutes=5),
                max_retries=3,
                retry_count=0,
                payload={},
            ),
            OrmScheduledJob(
                id=null_lease_stale_id,
                name=f"null_lease_{null_lease_stale_id}",
                status=JobStatus.RUNNING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                owner_token="worker-legacy",
                lease_expires_at=None,
                updated_at=(now - timedelta(minutes=5)).replace(tzinfo=None),
                max_retries=3,
                retry_count=0,
                payload={},
            ),
            OrmScheduledJob(
                id=active_job_id,
                name=f"active_{active_job_id}",
                status=JobStatus.RUNNING.value,
                next_run_at=now,
                target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                owner_token="worker-new",
                lease_expires_at=now + timedelta(minutes=5),
                max_retries=3,
                retry_count=0,
                payload={},
            ),
        ]
    )
    await test_session.flush()

    repo = SqlAlchemyJobRepository(test_session)
    swept_count = await repo.sweep_stuck_jobs(lock_lease_ms=5000)
    await test_session.flush()

    assert swept_count == 2

    expired_row = await test_session.get(OrmScheduledJob, expired_lease_id)
    null_lease_row = await test_session.get(OrmScheduledJob, null_lease_stale_id)
    active_row = await test_session.get(OrmScheduledJob, active_job_id)
    assert expired_row is not None and null_lease_row is not None and active_row is not None
    await test_session.refresh(expired_row)
    await test_session.refresh(null_lease_row)
    await test_session.refresh(active_row)

    assert expired_row.status == JobStatus.PENDING.value
    assert null_lease_row.status == JobStatus.PENDING.value
    assert active_row.status == JobStatus.RUNNING.value
