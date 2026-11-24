import asyncio
import inspect
from collections.abc import Awaitable
from typing import cast

import pytest
from notification.domain.constants import NotificationCleanupJobName
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from sqlalchemy.engine import make_url

from notification_jobs_worker.adapters.inbound.jobs.notification_outbox_cleanup_job import (
    NotificationOutboxCleanupJobHandler,
)
from notification_jobs_worker.bootstrap.container import WorkerContainer
from notification_jobs_worker.config.settings import get_settings
from notification_jobs_worker.main import main

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_main_execution():
    """
    Test the main worker boot sequence without mocks to satisfy coverage and enterprise standards.
    Boots the actual container, starts the relay, and shuts down via signal simulation.
    """
    # Run the worker as a background task
    worker_task = asyncio.create_task(main())

    # Let it boot and run the listener for a second
    await asyncio.sleep(1)
    assert not worker_task.done(), "Worker task should still be running"

    # Cancel the worker to trigger the finally block and shutdown sequence
    worker_task.cancel()

    # Wait for the worker to shut down naturally
    try:
        await asyncio.wait_for(worker_task, timeout=5.0)
    except asyncio.CancelledError:
        pass
    except TimeoutError:
        pytest.fail("Worker failed to shut down gracefully after cancellation")


async def test_job_dispatcher_execution():
    """Verify that job dispatcher processes cleanup and sweeper jobs end-to-end."""
    settings = get_settings()
    db_url = settings.database_url
    parsed = make_url(db_url)
    db_name = parsed.database or "global_db"
    if not db_name.endswith("_test"):
        db_name = f"{db_name}_test"
    db_url = parsed.set(database=db_name).render_as_string(hide_password=False)

    container = WorkerContainer()
    container.config.from_pydantic(settings)
    container.config.database_url.from_value(db_url)
    container.config.sns_topic_arn.from_value(settings.sns_topic_arn)
    container.config.aws_region.from_value(settings.aws_region)
    container.config.aws_endpoint_url.from_value(settings.aws_endpoint_url)
    container.config.sqs_notification_jobs_queue_url.from_value(
        settings.sqs_notification_jobs_queue_url
    )
    await cast(Awaitable[None], container.init_resources())

    dispatcher = container.job_dispatcher()
    while inspect.isawaitable(dispatcher):
        dispatcher = await dispatcher

    # Dispatch outbox cleanup job
    await dispatcher.dispatch(
        {
            "job_name": NotificationCleanupJobName.NOTIFICATION_OUTBOX_CLEANUP.value,
            "payload": {},
        }
    )

    # Dispatch outbox sweeper job
    await dispatcher.dispatch(
        {
            "job_name": NotificationCleanupJobName.NOTIFICATION_OUTBOX_SWEEPER.value,
            "payload": {},
        }
    )


class _FailingOutboxCleanupRepo(OutboxCleanupRepositoryPort):
    async def cleanup_outbox(self, retention_days: int) -> int:
        raise RuntimeError("Forced cleanup failure for integration coverage")


async def test_cleanup_job_handler_failure():
    """Verify NotificationOutboxCleanupJobHandler handles and re-raises exceptions."""
    handler = NotificationOutboxCleanupJobHandler(
        use_case=OutboxCleanerUseCase(repository=_FailingOutboxCleanupRepo())
    )
    with pytest.raises(RuntimeError, match="Forced cleanup failure for integration coverage"):
        await handler.execute()
