import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from database.session import get_session
from fastapi import Request


@pytest.mark.asyncio
async def test_get_session_missing_router() -> None:
    mock_request = MagicMock(spec=Request)
    mock_request.app.state = MagicMock()
    # Explicitly remove db_router
    del mock_request.app.state.db_router

    async_gen = get_session(mock_request)

    with pytest.raises(RuntimeError, match="DatabaseRouter not initialized in app state"):
        await async_gen.__anext__()


@pytest.mark.asyncio
async def test_get_session_missing_host_tenant() -> None:
    mock_request = MagicMock(spec=Request)
    mock_router = MagicMock()
    mock_request.app.state.db_router = mock_router

    mock_global_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_global_session.execute.return_value = mock_result

    async def mock_global_gen() -> Any:
        yield mock_global_session

    mock_router.get_global_session.return_value = mock_global_gen()

    async_gen = get_session(mock_request)

    with pytest.raises(RuntimeError, match="Host tenant \\(Tenant 0\\) not found in Global DB"):
        await async_gen.__anext__()


@pytest.mark.asyncio
async def test_get_session_success_and_commit() -> None:
    mock_request = MagicMock(spec=Request)
    mock_router = MagicMock()
    mock_request.app.state.db_router = mock_router

    mock_global_session = AsyncMock()
    mock_result = MagicMock()

    mock_tenant = MagicMock()
    mock_tenant.id = 0
    mock_shard = MagicMock()
    mock_shard.name = "shard_1"
    mock_shard.dsn = "postgresql+asyncpg://user:pass@localhost/db"

    mock_result.first.return_value = (mock_tenant, mock_shard)
    mock_global_session.execute.return_value = mock_result

    async def mock_global_gen() -> Any:
        yield mock_global_session

    mock_router.get_global_session.return_value = mock_global_gen()

    mock_tenant_session = AsyncMock()

    async def mock_tenant_gen() -> Any:
        yield mock_tenant_session

    mock_router.get_tenant_session.return_value = mock_tenant_gen()

    async_gen = get_session(mock_request)

    session = await async_gen.__anext__()
    assert session == mock_tenant_session

    # Simulate FastAPI finishing the request successfully
    with contextlib.suppress(StopAsyncIteration):
        await async_gen.__anext__()

    mock_tenant_session.commit.assert_called_once()
    mock_tenant_session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_get_session_exception_triggers_rollback() -> None:
    mock_request = MagicMock(spec=Request)
    mock_router = MagicMock()
    mock_request.app.state.db_router = mock_router

    mock_global_session = AsyncMock()
    mock_result = MagicMock()

    mock_tenant = MagicMock()
    mock_tenant.id = 0
    mock_shard = MagicMock()
    mock_shard.name = "shard_1"
    mock_shard.dsn = "postgresql+asyncpg://user:pass@localhost/db"

    mock_result.first.return_value = (mock_tenant, mock_shard)
    mock_global_session.execute.return_value = mock_result

    async def mock_global_gen() -> Any:
        yield mock_global_session

    mock_router.get_global_session.return_value = mock_global_gen()

    mock_tenant_session = AsyncMock()

    async def mock_tenant_gen() -> Any:
        yield mock_tenant_session

    mock_router.get_tenant_session.return_value = mock_tenant_gen()

    async_gen = get_session(mock_request)

    session = await async_gen.__anext__()
    assert session == mock_tenant_session

    # Simulate FastAPI catching an exception and throwing it back into the generator
    with pytest.raises(ValueError, match="Test error"):
        await async_gen.athrow(ValueError("Test error"))

    mock_tenant_session.commit.assert_not_called()
    mock_tenant_session.rollback.assert_called_once()
