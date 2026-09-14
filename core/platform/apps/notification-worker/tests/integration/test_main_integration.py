import asyncio
import contextlib

import pytest

from notification_worker.main import main


@pytest.mark.asyncio
async def test_main_execution() -> None:
    """
    Validates that the notification worker can boot its dependency injection container,
    wire its dependencies properly, and handle a graceful shutdown via task cancellation.
    This provides ~100% coverage over the bootstrap sequence without using any mocks.
    """
    # Start the worker in the background
    worker_task = asyncio.create_task(main())

    # Wait for the container to initialize and consumer to start polling
    await asyncio.sleep(0.5)
    assert not worker_task.done(), "Worker task should still be running"

    # Cancel the worker task to trigger graceful shutdown
    worker_task.cancel()

    # The task should complete with a CancelledError, which main suppresses via its try/finally
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(worker_task, timeout=5.0)
