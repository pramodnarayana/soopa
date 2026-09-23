import asyncio
import contextlib

import pytest

from edi_delivery_worker.main import main


@pytest.mark.asyncio
@pytest.mark.integration
async def test_worker_main_boot_and_shutdown() -> None:
    """
    Test that the root worker boot script initializes observability
    and boots the data_main task correctly, then shuts down.
    No monkeypatching is used.
    """
    task = asyncio.create_task(main())

    await asyncio.sleep(1.5)

    assert not task.done(), "Worker task should not exit prematurely"
    # Cancel the main task (which in turn cancels the data_task inside it)
    task.cancel()

    with contextlib.suppress(asyncio.CancelledError):
        await task
