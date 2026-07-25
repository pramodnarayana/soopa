import contextlib
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from database.session import get_session


@pytest.mark.asyncio
async def test_get_session_success() -> None:
    mock_request = MagicMock(spec=Request)
    mock_db_router = AsyncMock()
    mock_request.app.state.db_router = mock_db_router

    mock_session = AsyncMock()

    # Mock the new global DB resolution
    mock_global_session = AsyncMock()
    mock_row = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.id = 0
    mock_shard = MagicMock()
    mock_shard.name = "shard_1"
    mock_shard.dsn = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"

    # Ensure iterating the row unpacks to (tenant, shard)
    mock_row.__iter__.return_value = iter([mock_tenant, mock_shard])

    mock_global_result = MagicMock()
    mock_global_result.first.return_value = mock_row
    mock_global_session.execute.return_value = mock_global_result

    async def mock_global_gen() -> AsyncGenerator[AsyncMock, None]:
        yield mock_global_session

    mock_db_router.get_global_session = MagicMock(return_value=mock_global_gen())

    async def mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
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

    # Mock the new global DB resolution
    mock_global_session = AsyncMock()
    mock_row = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.id = 0
    mock_shard = MagicMock()
    mock_shard.name = "shard_1"
    mock_shard.dsn = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"

    mock_row.__iter__.return_value = iter([mock_tenant, mock_shard])
    mock_global_result = MagicMock()
    mock_global_result.first.return_value = mock_row
    mock_global_session.execute.return_value = mock_global_result

    async def mock_global_gen() -> AsyncGenerator[AsyncMock, None]:
        yield mock_global_session

    mock_db_router.get_global_session = MagicMock(return_value=mock_global_gen())

    async def mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    mock_db_router.get_tenant_session = MagicMock(return_value=mock_session_gen())

    gen = get_session(mock_request)
    await gen.__anext__()

    # Simulate an exception happening in the FastAPI route
    with pytest.raises(ValueError):
        await gen.athrow(ValueError("Route failed"))

    mock_session.rollback.assert_awaited_once()
