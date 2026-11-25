"""Unit tests for DatabaseJobDispatcher."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scheduler.adapters.outbound.messaging.database_job_dispatcher import DatabaseJobDispatcher
from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob


def _make_job(
    job_id: str = "job_001",
    name: str = "outbox_cleanup",
    target_queue: str | None = "notification-jobs.fifo",
) -> ScheduledJob:
    return ScheduledJob(
        id=job_id,
        name=name,
        target_queue=target_queue,
        payload={"retention_days": 7},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=300,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
        app_namespace="platform",
    )


@pytest.mark.asyncio
async def test_database_job_dispatcher_in_process_handler_execution() -> None:
    executed_jobs: list[ScheduledJob] = []

    async def on_cleanup(job: ScheduledJob) -> None:
        executed_jobs.append(job)

    dispatcher = DatabaseJobDispatcher()
    dispatcher.register_handler("outbox_cleanup", on_cleanup)

    job = _make_job(name="outbox_cleanup")
    await dispatcher.dispatch(job)

    assert len(executed_jobs) == 1
    assert executed_jobs[0].id == "job_001"


@pytest.mark.asyncio
async def test_database_job_dispatcher_missing_target_raises_value_error() -> None:
    dispatcher = DatabaseJobDispatcher()
    job = _make_job(name="unregistered_job", target_queue=None)
    with pytest.raises(ValueError, match="No in-process handler or target_queue defined"):
        await dispatcher.dispatch(job)


@pytest.mark.asyncio
async def test_database_job_dispatcher_raises_when_no_handler_and_no_database_queue() -> None:
    dispatcher = DatabaseJobDispatcher(database_queue=None)
    job = _make_job(name="unregistered_job", target_queue="notification-jobs.fifo")
    with pytest.raises(ValueError, match="DatabaseQueuePort is configured"):
        await dispatcher.dispatch(job)
