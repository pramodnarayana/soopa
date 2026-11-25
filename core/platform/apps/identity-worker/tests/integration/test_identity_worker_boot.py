import pytest

pytestmark = pytest.mark.integration

import asyncio
import os

import pytest
from identity_worker.config.settings import AppSettings as Settings
from identity_worker.main import main


@pytest.mark.asyncio
async def test_identity_worker_boots_and_shuts_down_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Narrow Integration Test that verifies the identity worker container
    can successfully wire its real infrastructure dependencies (PostgreSQL Single-Queue Pub/Sub)
    and then shut them down gracefully.
    """
    # Create the stop event that we'll use to gracefully shut down the worker
    stop_event = asyncio.Event()

    # Pass in the correct settings for the sovereign PostgreSQL integration test environment
    test_settings = Settings(
        app_env="test",
        database_url=os.environ["DATABASE_URL"],
        sqs_identity_sync_queue_url="db://identity-events.fifo",
        aws_region="us-east-1",
        aws_endpoint_url=None,
    )

    # Start the worker in the background
    worker_task = asyncio.create_task(main(stop_event=stop_event, settings=test_settings))

    try:
        # Give it a second to boot up all infrastructure listeners and consumers
        await asyncio.sleep(1.0)
    finally:
        # Trigger the graceful shutdown
        stop_event.set()

    # Await the worker shutdown (with a timeout so we don't hang if it's stuck)
    await asyncio.wait_for(worker_task, timeout=5.0)
