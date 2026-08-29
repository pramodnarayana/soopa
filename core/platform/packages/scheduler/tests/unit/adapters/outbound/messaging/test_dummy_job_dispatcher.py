import pytest

from scheduler.adapters.outbound.messaging.dummy_job_dispatcher import DummyJobDispatcher
from scheduler.domain.models import ScheduledJob


@pytest.mark.asyncio
async def test_dummy_job_dispatcher():
    dispatcher = DummyJobDispatcher()
    job = ScheduledJob(
        id="job-123",
        name="test-job",
        status="PENDING",
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=None,
        target_queue="test-queue",
        payload={"foo": "bar"},
    )

    await dispatcher.dispatch(job)
    # Just ensure it runs without error
