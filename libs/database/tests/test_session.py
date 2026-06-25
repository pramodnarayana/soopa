import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from database.session import get_session
from fastapi import Request


@pytest.mark.asyncio
async def test_get_session_success() -> None:
    mock_request = MagicMock(spec=Request)
    mock_db_router = AsyncMock()
    mock_request.app.state.db_router = mock_db_router

    mock_session = AsyncMock()

    async def mock_session_gen():
        yield mock_session

    mock_db_router.get_tenant_session = MagicMock(return_value=mock_session_gen())

    gen = get_session(mock_request)
    session = await gen.__anext__()

    assert session == mock_session
    mock_db_router.get_tenant_session.assert_called_once_with(
        tenant_id=0,
        shard_key="shard_1",
        shard_url="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
    )

    # Test cleanup/commit
    with contextlib.suppress(StopAsyncIteration):
        await gen.__anext__()

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_rollback_on_exception() -> None:
    mock_request = MagicMock(spec=Request)
    mock_db_router = AsyncMock()
    mock_request.app.state.db_router = mock_db_router

    mock_session = AsyncMock()

    async def mock_session_gen():
        yield mock_session

    mock_db_router.get_tenant_session = MagicMock(return_value=mock_session_gen())

    gen = get_session(mock_request)
    await gen.__anext__()

    # Simulate an exception happening in the FastAPI route
    with pytest.raises(ValueError):
        await gen.athrow(ValueError("Route failed"))

    mock_session.rollback.assert_awaited_once()
