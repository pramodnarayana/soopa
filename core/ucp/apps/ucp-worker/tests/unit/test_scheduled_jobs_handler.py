import pytest
from seedwork import generate_id

from ucp_worker.core.job_registry import JobHandlerRegistry
from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job
from ucp_worker.scheduled_jobs_handler import process_scheduled_job


class TrackingJobHandler(JobHandlerPort):
    def __init__(self) -> None:
        self.executed_jobs: list[Job] = []

    async def execute(self, job: Job) -> None:
        self.executed_jobs.append(job)


@pytest.mark.asyncio
async def test_process_scheduled_job_success() -> None:
    registry = JobHandlerRegistry()
    handler = TrackingJobHandler()
    registry.register("test_job", handler)

    job_id = generate_id("id")
    message = {"job_id": job_id, "job_name": "test_job", "payload": {"key": "value"}}

    await process_scheduled_job(message, registry=registry)

    assert len(handler.executed_jobs) == 1
    job = handler.executed_jobs[0]
    assert str(job.id) == job_id
    assert job.name == "test_job"
    assert job.payload == {"key": "value"}


@pytest.mark.asyncio
async def test_process_scheduled_job_missing_identifiers() -> None:
    registry = JobHandlerRegistry()
    message = {"payload": {}}

    # Should log and return without executing or raising
    await process_scheduled_job(message, registry=registry)


@pytest.mark.asyncio
async def test_process_scheduled_job_missing_registry() -> None:
    job_id = generate_id("id")
    message = {
        "job_id": job_id,
        "job_name": "test_job",
    }
    # Should log and return without raising
    await process_scheduled_job(message)


@pytest.mark.asyncio
async def test_process_scheduled_job_unknown_job_name() -> None:
    registry = JobHandlerRegistry()
    job_id = generate_id("id")
    message = {
        "job_id": job_id,
        "job_name": "unknown_job",
    }
    with pytest.raises(ValueError, match="Unknown scheduled job name: unknown_job"):
        await process_scheduled_job(message, registry=registry)
