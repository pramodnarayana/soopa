import asyncio

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

from edi_delivery_worker.data.main import main


async def test_data_main_boot_and_shutdown() -> None:
    """
    Test that the data worker boots successfully, wires all dependencies,
    connects to SQS/Postgres, and shuts down cleanly via stop_event.
    No monkeypatching is used; this connects to real LocalStack and PostgreSQL.
    """
    stop_event = asyncio.Event()
    task = asyncio.create_task(main(stop_event=stop_event))

    # Allow worker initialization to complete
    await asyncio.sleep(0.5)

    assert not task.done(), "Worker task should not exit prematurely"

    # Signal graceful shutdown via architectural stop_event contract
    stop_event.set()

    # Worker should terminate cleanly within timeout
    await asyncio.wait_for(task, timeout=5.0)
