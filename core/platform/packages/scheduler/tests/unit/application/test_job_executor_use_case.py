import asyncio
from datetime import UTC, datetime

from scheduler.application.job_executor_use_case import JobExecutorUseCase
from scheduler.domain.constants import JobStatus
from scheduler.domain.models import ScheduledJob
from tests.fakes.fake_dispatcher import FakeJobDispatcher
from tests.fakes.fake_uow import FakeJobRepository, FakeSchedulerUow


def test_claim_and_execute_job_completed():
    repo = FakeJobRepository()
    job = ScheduledJob(
        id="job-1",
        name="test_job",
        target_queue="test_queue",
        payload={"foo": "bar"},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )
    repo.jobs[job.id] = job

    dispatcher = FakeJobDispatcher()

    # Factory returning our fake uow
    def uow_factory():
        return FakeSchedulerUow(repo)

    use_case = JobExecutorUseCase(uow_factory=uow_factory, dispatcher=dispatcher)

    # Run it

    asyncio.run(use_case.execute(worker_id="worker-1", limit=10, lock_lease_ms=5000))

    assert len(dispatcher.dispatched_jobs) == 1
    assert dispatcher.dispatched_jobs[0].id == "job-1"

    # Verify state transitions
    updated_job = repo.jobs["job-1"]
    assert updated_job.status == JobStatus.COMPLETED


def test_claim_and_execute_job_reschedules_interval():
    repo = FakeJobRepository()
    job = ScheduledJob(
        id="job-2",
        name="interval_job",
        target_queue="test_queue",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=60,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )
    repo.jobs[job.id] = job

    dispatcher = FakeJobDispatcher()

    use_case = JobExecutorUseCase(uow_factory=lambda: FakeSchedulerUow(repo), dispatcher=dispatcher)

    asyncio.run(use_case.execute(worker_id="worker-1", limit=10, lock_lease_ms=5000))

    assert len(dispatcher.dispatched_jobs) == 1
    updated_job = repo.jobs["job-2"]
    assert updated_job.status == JobStatus.PENDING
    assert updated_job.retry_count == 0
    assert updated_job.next_run_at is not None
    assert updated_job.next_run_at > datetime.now(UTC)


def test_claim_and_execute_job_reschedules_cron():
    repo = FakeJobRepository()
    job = ScheduledJob(
        id="job-3",
        name="cron_job",
        target_queue="test_queue",
        payload={},
        status=JobStatus.PENDING,
        cron_expression="* * * * *",  # Every minute
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )
    repo.jobs[job.id] = job

    dispatcher = FakeJobDispatcher()
    use_case = JobExecutorUseCase(uow_factory=lambda: FakeSchedulerUow(repo), dispatcher=dispatcher)

    asyncio.run(use_case.execute(worker_id="worker-1", limit=10, lock_lease_ms=5000))

    assert len(dispatcher.dispatched_jobs) == 1
    updated_job = repo.jobs["job-3"]
    assert updated_job.status == JobStatus.PENDING
    assert updated_job.retry_count == 0
    assert updated_job.next_run_at is not None
    assert updated_job.next_run_at > datetime.now(UTC)


def test_claim_and_execute_job_retry_backoff():
    repo = FakeJobRepository()
    job = ScheduledJob(
        id="job-fail-1",
        name="failing_job",
        target_queue="test_queue",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )
    repo.jobs[job.id] = job

    dispatcher = FakeJobDispatcher()
    dispatcher.should_fail = True  # Force it to throw

    use_case = JobExecutorUseCase(uow_factory=lambda: FakeSchedulerUow(repo), dispatcher=dispatcher)

    asyncio.run(use_case.execute(worker_id="worker-1", limit=10, lock_lease_ms=5000))

    updated_job = repo.jobs["job-fail-1"]
    assert updated_job.status == JobStatus.PENDING
    assert updated_job.retry_count == 1
    assert updated_job.next_run_at > datetime.now(UTC)


def test_claim_and_execute_job_max_retries():
    repo = FakeJobRepository()
    job = ScheduledJob(
        id="job-fail-max",
        name="failing_job_max",
        target_queue="test_queue",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=3,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )
    repo.jobs[job.id] = job

    dispatcher = FakeJobDispatcher()
    dispatcher.should_fail = True

    use_case = JobExecutorUseCase(uow_factory=lambda: FakeSchedulerUow(repo), dispatcher=dispatcher)

    asyncio.run(use_case.execute(worker_id="worker-1", limit=10, lock_lease_ms=5000))

    updated_job = repo.jobs["job-fail-max"]
    assert updated_job.status == JobStatus.FAILED
