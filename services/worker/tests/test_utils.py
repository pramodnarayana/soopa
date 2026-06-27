from unittest.mock import AsyncMock, MagicMock

import pytest
from database.connection import DatabaseRouter
from worker.utils import TenantResolver

pytestmark = pytest.mark.asyncio


async def test_tenant_resolver_cache_hit() -> None:
    mock_router = MagicMock(spec=DatabaseRouter)

    resolver = TenantResolver(db_router=mock_router)
    resolver._cache[1] = ("shard1", "postgresql://db1")

    shard_name, shard_url = await resolver.resolve(1)

    assert shard_name == "shard1"
    assert shard_url == "postgresql://db1"
    mock_router.get_global_session.assert_not_called()


async def test_tenant_resolver_cache_miss_success() -> None:
    mock_router = MagicMock(spec=DatabaseRouter)
    mock_gen = AsyncMock()
    mock_router.get_global_session.return_value = mock_gen

    mock_session = AsyncMock()
    mock_gen.__anext__.return_value = mock_session

    mock_result = MagicMock()
    # Return (Tenant, DatabaseShard)
    mock_shard = MagicMock()
    mock_shard.name = "shard1"
    mock_shard.dsn = "postgresql://db1"
    mock_result.first.return_value = (MagicMock(), mock_shard)

    mock_session.execute.return_value = mock_result

    resolver = TenantResolver(db_router=mock_router)
    shard_name, shard_url = await resolver.resolve(1)

    assert shard_name == "shard1"
    assert shard_url == "postgresql://db1"
    assert 1 in resolver._cache


async def test_tenant_resolver_cache_miss_not_found() -> None:
    mock_router = MagicMock(spec=DatabaseRouter)
    mock_gen = AsyncMock()
    mock_router.get_global_session.return_value = mock_gen

    mock_session = AsyncMock()
    mock_gen.__anext__.return_value = mock_session

    mock_result = MagicMock()
    mock_result.first.return_value = None

    mock_session.execute.return_value = mock_result

    resolver = TenantResolver(db_router=mock_router)

    with pytest.raises(ValueError, match="Tenant 1 not found in Global DB"):
        await resolver.resolve(1)
