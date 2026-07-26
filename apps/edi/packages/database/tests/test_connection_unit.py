from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.connection import DatabaseRouter


@pytest.fixture
def mock_create_engine() -> Any:
    with patch("database.connection.create_async_engine") as mock:
        # Use a lambda as side_effect to return a fresh AsyncMock each time it's called
        mock.side_effect = lambda *args, **kwargs: AsyncMock()
        yield mock


@pytest.fixture
def router(mock_create_engine: Any) -> DatabaseRouter:
    return DatabaseRouter(global_db_url="sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_database_router_initializes_global_engine(
    mock_create_engine: Any, router: DatabaseRouter
) -> None:
    assert "global" in router._engines
    mock_create_engine.assert_called_once_with(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@pytest.mark.asyncio
async def test_get_engine_creates_new_engine(
    mock_create_engine: Any, router: DatabaseRouter
) -> None:
    engine = await router.get_engine("shard_1", "postgresql+asyncpg://user:pass@localhost/db")
    assert "shard_1" in router._engines
    assert router._engines["shard_1"] == engine
    assert mock_create_engine.call_count == 2


@pytest.mark.asyncio
async def test_get_engine_returns_cached_engine(
    mock_create_engine: Any, router: DatabaseRouter
) -> None:
    engine1 = await router.get_engine("shard_1", "postgresql+asyncpg://user:pass@localhost/db")
    engine2 = await router.get_engine("shard_1", "postgresql+asyncpg://user:pass@localhost/db")

    assert engine1 == engine2
    assert mock_create_engine.call_count == 2  # Only called once for global, once for shard_1


@pytest.mark.asyncio
async def test_get_engine_raises_error_without_url(router: DatabaseRouter) -> None:
    with pytest.raises(ValueError, match="Engine for shard_2 not found and no URL provided."):
        await router.get_engine("shard_2")


@pytest.mark.asyncio
async def test_get_global_session(router: DatabaseRouter) -> None:
    mock_factory = MagicMock()
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_factory.return_value = mock_cm

    with patch("database.connection.async_sessionmaker", return_value=mock_factory):
        async_gen = router.get_global_session()
        session = await async_gen.__anext__()
        assert session == mock_session


@pytest.mark.asyncio
async def test_get_tenant_session_enforces_rls(router: DatabaseRouter) -> None:
    mock_factory = MagicMock()
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_factory.return_value = mock_cm

    with patch("database.connection.async_sessionmaker", return_value=mock_factory):
        async_gen = router.get_tenant_session("123", "shard_1", "postgresql+asyncpg://url")
        session = await async_gen.__anext__()

        assert session == mock_session
        session.execute.assert_called_once()
        # Ensure RLS was enforced via set_config (parameterized, transaction-local)
        call_args = session.execute.call_args
        sql_str = str(call_args[0][0])
        assert "set_config" in sql_str
        assert "app.current_tenant" in sql_str
        # Verify tenant_id was passed as a parameter
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params["tenant_id"] == "123"


@pytest.mark.asyncio
async def test_close_all_disposes_engines(router: DatabaseRouter) -> None:
    engine1 = await router.get_engine("shard_1", "postgresql+asyncpg://user:pass@localhost/db")

    # Pre-condition
    assert len(router._engines) == 2

    # Get a reference to the global engine which was created implicitly on init
    global_engine = router._engines["global"]

    await router.close_all()

    assert len(router._engines) == 0
    assert engine1.dispose.call_count == 1
    assert global_engine.dispose.call_count == 1
