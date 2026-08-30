import uuid

import pytest

from edi_background_worker.scheduled_jobs_handler import process_scheduled_job


@pytest.mark.asyncio
async def test_process_scheduled_job_missing_id() -> None:
    # Should log warning and return
    await process_scheduled_job({"job_name": "test"})


@pytest.mark.asyncio
async def test_process_scheduled_job_missing_name() -> None:
    # Should log warning and return
    await process_scheduled_job({"job_id": str(uuid.uuid4())})


@pytest.mark.asyncio
async def test_process_scheduled_job_missing_registry() -> None:
    # Should log error and return
    await process_scheduled_job({"job_id": str(uuid.uuid4()), "job_name": "test_job"})


@pytest.mark.asyncio
async def test_process_scheduled_job_unknown_job() -> None:
    class FakeRegistry:
        def get(self, name: str):
            return None

    registry = FakeRegistry()
    with pytest.raises(ValueError, match="Unknown scheduled job name: unknown_job"):
        await process_scheduled_job(
            {"job_id": str(uuid.uuid4()), "job_name": "unknown_job"},
            registry=registry,  # type: ignore
        )


@pytest.mark.asyncio
async def test_process_scheduled_job_success() -> None:
    class FakeHandler:
        def __init__(self):
            self.executed_job = None

        async def execute(self, job) -> None:
            self.executed_job = job

    class FakeRegistry:
        def __init__(self, handler):
            self.handler = handler

        def get(self, name: str):
            return self.handler

    mock_handler = FakeHandler()
    registry = FakeRegistry(mock_handler)

    job_id = str(uuid.uuid4())
    await process_scheduled_job(
        {"job_id": job_id, "job_name": "known_job", "payload": {"foo": "bar"}},
        registry=registry,  # type: ignore
    )

    assert mock_handler.executed_job is not None
    job = mock_handler.executed_job
    assert str(job.id) == job_id
    assert job.name == "known_job"
    assert job.payload == {"foo": "bar"}
