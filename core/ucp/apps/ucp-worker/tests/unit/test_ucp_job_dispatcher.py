from unittest.mock import AsyncMock

import pytest

from ucp_worker.adapters.inbound.workers.ucp_job_dispatcher import UcpJobDispatcher


@pytest.mark.asyncio
async def test_dispatch_rejects_non_string_job_name() -> None:
    dispatcher = UcpJobDispatcher()

    with pytest.raises(ValueError, match="Unknown UCP job name"):
        await dispatcher.dispatch({"job_name": []})


@pytest.mark.asyncio
async def test_dispatch_preserves_unknown_string_job_handling() -> None:
    dispatcher = UcpJobDispatcher()

    with pytest.raises(ValueError, match="Unknown UCP job name: missing"):
        await dispatcher.dispatch({"job_name": "missing"})


@pytest.mark.asyncio
async def test_dispatch_calls_registered_handler() -> None:
    dispatcher = UcpJobDispatcher()
    handler = AsyncMock()
    message = {"job_name": "cleanup"}
    dispatcher.subscribe("cleanup", handler)

    await dispatcher.dispatch(message)

    handler.assert_awaited_once_with(message)
