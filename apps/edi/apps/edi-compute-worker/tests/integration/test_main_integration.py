import asyncio
import contextlib

import pytest

from compute_worker.main import main


@pytest.mark.asyncio
async def test_main_execution() -> None:
    """
    Test that the worker main function boots the application container,
    starts the background SQS poller successfully without exceptions,
    and then correctly tears down everything upon receiving a cancellation signal.
    """
    # Create the task for main()
    worker_task = asyncio.create_task(main())

    # Yield control to the event loop so main() can execute and start the manager
    await asyncio.sleep(0.5)

    # Cancel the task to simulate a shutdown signal
    worker_task.cancel()

    # The task should complete with a CancelledError, which main suppresses via its try/finally
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task
