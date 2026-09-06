from unittest.mock import AsyncMock

import pytest

from edi_background_worker.adapters.inbound.workers.edi_job_dispatcher import EdiJobDispatcher


@pytest.mark.asyncio
async def test_dispatch_rejects_non_string_job_name() -> None:
    dispatcher = EdiJobDispatcher()

    with pytest.raises(ValueError, match="Unknown EDI job name"):
        await dispatcher.dispatch({"job_name": []})


@pytest.mark.asyncio
async def test_dispatch_preserves_unknown_string_job_handling() -> None:
    dispatcher = EdiJobDispatcher()

    with pytest.raises(ValueError, match="Unknown EDI job name: missing"):
        await dispatcher.dispatch({"job_name": "missing"})


@pytest.mark.asyncio
async def test_dispatch_calls_registered_handler() -> None:
    dispatcher = EdiJobDispatcher()
    handler = AsyncMock()
    message = {"job_name": "cleanup"}
    dispatcher.subscribe("cleanup", handler)

    await dispatcher.dispatch(message)

    handler.assert_awaited_once_with(message)
