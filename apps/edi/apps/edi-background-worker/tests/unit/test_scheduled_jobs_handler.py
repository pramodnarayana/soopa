import uuid
from unittest.mock import AsyncMock, MagicMock

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
    registry = MagicMock()
    registry.get.return_value = None
    with pytest.raises(ValueError, match="Unknown scheduled job name: unknown_job"):
        await process_scheduled_job(
            {"job_id": str(uuid.uuid4()), "job_name": "unknown_job"}, registry=registry
        )


@pytest.mark.asyncio
async def test_process_scheduled_job_success() -> None:
    registry = MagicMock()
    mock_handler = AsyncMock()
    registry.get.return_value = mock_handler

    job_id = str(uuid.uuid4())
    await process_scheduled_job(
        {"job_id": job_id, "job_name": "known_job", "payload": {"foo": "bar"}}, registry=registry
    )

    mock_handler.execute.assert_awaited_once()
    job = mock_handler.execute.call_args[0][0]
    assert str(job.id) == job_id
    assert job.name == "known_job"
    assert job.payload == {"foo": "bar"}
