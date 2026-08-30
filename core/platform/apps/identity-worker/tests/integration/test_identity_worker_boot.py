import asyncio

import pytest
from identity_worker.bootstrap.config import Settings
from identity_worker.main import main


@pytest.mark.asyncio
async def test_identity_worker_boots_and_shuts_down_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Narrow Integration Test (E2E) that verifies the identity worker container
    can successfully wire its real infrastructure dependencies (Postgres, SQS, Zitadel)
    and then shut them down gracefully.

    This replaces mocked unit tests for container.py and main.py by actually
    running the worker loop for a brief period against real infrastructure.
    """
    # Create the stop event that we'll use to gracefully shut down the worker
    stop_event = asyncio.Event()

    # Pass in the correct settings for the integration test environment
    test_settings = Settings(
        app_env="test",
        database_url="postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global",
        sqs_identity_sync_queue_url="http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/identity-events.fifo",
        aws_region="us-east-1",
        aws_endpoint_url="http://localhost:4566",
    )

    # We set these in environ as well for any internal boto3 clients that might rely on them
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

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
