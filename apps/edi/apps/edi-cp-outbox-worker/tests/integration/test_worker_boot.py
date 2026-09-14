import asyncio

import pytest
from database.router import DatabaseRouterPort

from edi_cp_outbox_worker.bootstrap.container import WorkerContainer


@pytest.mark.asyncio
@pytest.mark.integration
async def test_edi_cp_worker_boots_and_shuts_down_gracefully(
    db_router: DatabaseRouterPort,
) -> None:
    """
    Narrow Integration Test that verifies the EDI CP worker container
    can successfully wire its real infrastructure dependencies (Postgres, SNS, SQS)
    and then shut them down gracefully.

    This avoids mocks by relying on the standard .env values (like LocalStack
    and Postgres URLs) loaded by conftest.py.
    """
    container = WorkerContainer()

    # Use the test-provided db_router so we connect to the isolated test database
    container.db_router = db_router

    container.wire()

    # Start the worker background tasks (SQS polling, Postgres NOTIFY listening)
    await container.start()

    try:
        # Give it a brief moment to establish connections
        await asyncio.sleep(0.5)
    finally:
        # Trigger the graceful shutdown
        await container.dispose()
