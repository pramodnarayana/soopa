"""Pure zero-mock Phase 4 unit tests for SqlAlchemyJobRepository ORM mapper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from database.models.scheduling import ScheduledJob as OrmScheduledJob
from database.provider import DatabaseProvider
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from scheduler.adapters.outbound.database.sqlalchemy_job_repository import SqlAlchemyJobRepository
from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob
from tests.fakes.fake_uow import FakeJobRepository


def test_sqlalchemy_job_repository_orm_to_domain_mapper() -> None:
    next_run = datetime.now(UTC)
    job_id = generate_id(SystemIdPrefix.JOB.value)

    orm_job = OrmScheduledJob(
        id=job_id,
        name="edi_outbox_sweeper",
        target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/edi-jobs",
        payload={"batch_size": 100},
        status=JobStatus.RUNNING.value,
        cron_expression="*/5 * * * *",
        interval_seconds=None,
        retry_count=1,
        max_retries=5,
        next_run_at=next_run,
        app_namespace="edi",
    )

    domain_job = SqlAlchemyJobRepository._to_domain_model(orm_job)
    assert domain_job.id == job_id
    assert domain_job.name == "edi_outbox_sweeper"
    assert domain_job.status == JobStatus.RUNNING
    assert domain_job.payload == {"batch_size": 100}
    assert domain_job.cron_expression == "*/5 * * * *"
    assert domain_job.interval_seconds is None
    assert domain_job.retry_count == 1
    assert domain_job.max_retries == 5
    assert domain_job.next_run_at == next_run
    assert domain_job.app_namespace == "edi"


@pytest.mark.asyncio
async def test_sqlalchemy_job_repository_claims_due_dated_jobs_ahead_of_null_backlog() -> None:
    compiled_pg_sql = str(
        SqlAlchemyJobRepository._build_claimable_ids_subquery(limit=2).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "scheduling.scheduled_jobs.next_run_at IS NULL" in compiled_pg_sql
    assert "scheduling.scheduled_jobs.next_run_at <= now()" in compiled_pg_sql
    assert (
        "ORDER BY scheduling.scheduled_jobs.next_run_at ASC NULLS LAST, "
        "scheduling.scheduled_jobs.id ASC"
    ) in compiled_pg_sql

    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    async with provider.session_factory() as session:
        await session.execute(text("ATTACH DATABASE ':memory:' AS scheduling"))
        await session.execute(
            text(
                """
                CREATE TABLE scheduling.scheduled_jobs (
                    id VARCHAR(128) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    payload JSON NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    next_run_at TIMESTAMP NULL,
                    interval_seconds INTEGER NULL,
                    min_interval_seconds INTEGER NULL,
                    max_interval_seconds INTEGER NULL,
                    cron_expression VARCHAR(100) NULL,
                    timezone VARCHAR(50) NULL,
                    target_queue VARCHAR(255) NULL,
                    app_namespace VARCHAR(255) NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    error_message TEXT NULL,
                    lease_expires_at TIMESTAMP NULL,
                    owner_token VARCHAR(255) NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        session.add_all(
            [
                OrmScheduledJob(
                    id="sys_job_03_due",
                    name="due_job",
                    status=JobStatus.PENDING.value,
                    next_run_at=now_naive - timedelta(seconds=30),
                    target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                    payload={"kind": "due"},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
                OrmScheduledJob(
                    id="sys_job_02_null_b",
                    name="null_job_b",
                    status=JobStatus.PENDING.value,
                    next_run_at=None,
                    target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                    payload={"kind": "null_b"},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
                OrmScheduledJob(
                    id="sys_job_01_null_a",
                    name="null_job_a",
                    status=JobStatus.PENDING.value,
                    next_run_at=None,
                    target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                    payload={"kind": "null_a"},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
                OrmScheduledJob(
                    id="sys_job_04_future",
                    name="future_job",
                    status=JobStatus.PENDING.value,
                    next_run_at=now_naive + timedelta(hours=1),
                    target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/q1",
                    payload={"kind": "future"},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
            ]
        )
        await session.flush()

        top_two_records = (
            (
                await session.execute(
                    select(OrmScheduledJob).where(
                        OrmScheduledJob.id.in_(
                            SqlAlchemyJobRepository._build_claimable_ids_subquery(limit=2)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        first_batch = SqlAlchemyJobRepository._sort_claimed_jobs(
            [SqlAlchemyJobRepository._to_domain_model(record) for record in top_two_records]
        )
        assert [job.id for job in first_batch] == ["sys_job_03_due", "sys_job_01_null_a"]

        all_claimable_records = (
            (
                await session.execute(
                    select(OrmScheduledJob).where(
                        OrmScheduledJob.id.in_(
                            SqlAlchemyJobRepository._build_claimable_ids_subquery(limit=10)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        full_batch = SqlAlchemyJobRepository._sort_claimed_jobs(
            [SqlAlchemyJobRepository._to_domain_model(record) for record in all_claimable_records]
        )
        assert [job.id for job in full_batch] == [
            "sys_job_03_due",
            "sys_job_01_null_a",
            "sys_job_02_null_b",
        ]

    await provider.engine.dispose()


@pytest.mark.asyncio
async def test_fake_job_repository_orders_due_dated_ahead_of_null_and_skips_future() -> None:
    now = datetime.now(UTC)
    repo = FakeJobRepository()
    repo.jobs["sys_job_due"] = ScheduledJob(
        id="sys_job_due",
        name="due",
        target_queue="q1",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=now - timedelta(seconds=5),
    )
    repo.jobs["sys_job_null_b"] = ScheduledJob(
        id="sys_job_null_b",
        name="null_initial_b",
        target_queue="q1",
        payload={},
        status=JobStatus.PENDING,
        cron_expression="*/5 * * * *",
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=None,
    )
    repo.jobs["sys_job_null_a"] = ScheduledJob(
        id="sys_job_null_a",
        name="null_initial_a",
        target_queue="q1",
        payload={},
        status=JobStatus.PENDING,
        cron_expression="*/5 * * * *",
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=None,
    )
    repo.jobs["sys_job_future"] = ScheduledJob(
        id="sys_job_future",
        name="future",
        target_queue="q1",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=60,
        retry_count=0,
        max_retries=3,
        next_run_at=now + timedelta(minutes=10),
    )

    claimed = await repo.claim_next_jobs(worker_id="w-1", limit=2, lock_lease_ms=5000)
    assert [j.id for j in claimed] == ["sys_job_due", "sys_job_null_a"]


@pytest.mark.asyncio
async def test_sqlalchemy_job_repository_active_namespaces_subquery() -> None:
    # 1. Parameterized SQL verification
    sql_with_filter = str(
        SqlAlchemyJobRepository._build_claimable_ids_subquery(
            limit=5, active_namespaces=["platform", "edi"]
        ).compile(dialect=postgresql.dialect())
    )
    assert "scheduling.scheduled_jobs.app_namespace IN" in sql_with_filter

    sql_no_filter = str(
        SqlAlchemyJobRepository._build_claimable_ids_subquery(
            limit=5, active_namespaces=None
        ).compile(dialect=postgresql.dialect())
    )
    assert "app_namespace" not in sql_no_filter

    # 2. SQLite in-memory behavioral verification
    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    async with provider.session_factory() as session:
        await session.execute(text("ATTACH DATABASE ':memory:' AS scheduling"))
        await session.execute(
            text(
                """
                CREATE TABLE scheduling.scheduled_jobs (
                    id VARCHAR(128) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    payload JSON NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    next_run_at TIMESTAMP NULL,
                    interval_seconds INTEGER NULL,
                    min_interval_seconds INTEGER NULL,
                    max_interval_seconds INTEGER NULL,
                    cron_expression VARCHAR(100) NULL,
                    timezone VARCHAR(50) NULL,
                    target_queue VARCHAR(255) NULL,
                    app_namespace VARCHAR(255) NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    error_message TEXT NULL,
                    lease_expires_at TIMESTAMP NULL,
                    owner_token VARCHAR(255) NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        session.add_all(
            [
                OrmScheduledJob(
                    id="job_edi_1",
                    name="edi_job",
                    status=JobStatus.PENDING.value,
                    next_run_at=now_naive - timedelta(seconds=10),
                    target_queue="edi-queue",
                    app_namespace="edi",
                    payload={},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
                OrmScheduledJob(
                    id="job_ip_1",
                    name="ip_job",
                    status=JobStatus.PENDING.value,
                    next_run_at=now_naive - timedelta(seconds=10),
                    target_queue="ip-queue",
                    app_namespace="ip",
                    payload={},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
                OrmScheduledJob(
                    id="job_platform_1",
                    name="platform_job",
                    status=JobStatus.PENDING.value,
                    next_run_at=now_naive - timedelta(seconds=10),
                    target_queue="platform-queue",
                    app_namespace="platform",
                    payload={},
                    max_retries=3,
                    retry_count=0,
                    created_at=now_naive,
                    updated_at=now_naive,
                ),
            ]
        )
        await session.flush()

        # Claim with active_namespaces = ["platform", "edi"]
        claimed_ids = (
            (
                await session.execute(
                    select(OrmScheduledJob.id).where(
                        OrmScheduledJob.id.in_(
                            SqlAlchemyJobRepository._build_claimable_ids_subquery(
                                limit=10, active_namespaces=["platform", "edi"]
                            )
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(claimed_ids) == {"job_edi_1", "job_platform_1"}
        assert "job_ip_1" not in claimed_ids

        # Claim with active_namespaces = None (all claimed)
        all_ids = (
            (
                await session.execute(
                    select(OrmScheduledJob.id).where(
                        OrmScheduledJob.id.in_(
                            SqlAlchemyJobRepository._build_claimable_ids_subquery(
                                limit=10, active_namespaces=None
                            )
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(all_ids) == {"job_edi_1", "job_ip_1", "job_platform_1"}

    await provider.engine.dispose()


@pytest.mark.asyncio
async def test_fake_job_repository_filters_by_active_namespaces() -> None:
    now = datetime.now(UTC)
    repo = FakeJobRepository()
    repo.jobs["job_edi"] = ScheduledJob(
        id="job_edi",
        name="edi",
        target_queue="q1",
        app_namespace="edi",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=now - timedelta(seconds=1),
    )
    repo.jobs["job_ip"] = ScheduledJob(
        id="job_ip",
        name="ip",
        target_queue="q2",
        app_namespace="ip",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=now - timedelta(seconds=1),
    )

    claimed_edi = await repo.claim_next_jobs(
        worker_id="w-1", limit=10, lock_lease_ms=5000, active_namespaces=["platform", "edi"]
    )
    assert [j.id for j in claimed_edi] == ["job_edi"]
