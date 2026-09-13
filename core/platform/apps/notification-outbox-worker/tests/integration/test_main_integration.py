import asyncio

import pytest

from notification_outbox_worker.main import main


@pytest.mark.asyncio
@pytest.mark.integration
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
