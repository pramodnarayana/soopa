import asyncio

import pytest
from pydantic import ValidationError

from edi_delivery_worker.data.main import main


@pytest.mark.asyncio
@pytest.mark.integration
async def test_data_main_boot_and_shutdown() -> None:
    """
    Test that the data worker boots successfully, wires all dependencies,
    connects to SQS/Postgres, and shuts down cleanly on cancellation.
    No monkeypatching is used; this connects to real LocalStack and PostgreSQL.
    """
    task = asyncio.create_task(main())

    # Let the worker boot up and initialize all SqsConsumerManagers
    await asyncio.sleep(1.5)

    assert not task.done(), "Worker task should not exit prematurely"
    # Cancel the task to trigger the finally block (graceful shutdown)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass
    except ValidationError:
        # If the environment isn't fully set up for tests, we catch this,
        # but in CI the env should be valid.
        raise
