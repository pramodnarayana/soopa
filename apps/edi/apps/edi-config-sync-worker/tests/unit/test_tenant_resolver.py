from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from edi.adapters.outbound.database.tenant_resolver import TenantResolver


@pytest.mark.asyncio
async def test_tenant_resolver_success() -> None:
    mock_db_router = MagicMock()
    mock_global_session = AsyncMock()
    mock_db_router.get_global_session.return_value = mock_global_session

    class MockRow:
        def __init__(self, name: str, dsn: str) -> None:
            self.name = name
            self.dsn = dsn

    class MockResult:
        def first(self) -> Any:
            return (None, MockRow("ucp_shard_1", "postgresql://user:pass@host/db"))

    mock_global_session.__anext__.return_value = mock_global_session
    mock_global_session.execute.return_value = MockResult()

    resolver = TenantResolver(db_router=mock_db_router, ttl_secs=300)

    # First resolve should hit DB
    shard_name, shard_dsn = await resolver.resolve(tenant_id="1")
    assert shard_name == "ucp_shard_1"
    assert shard_dsn == "postgresql://user:pass@host/db"
    mock_global_session.execute.assert_awaited_once()

    # Second resolve should hit cache
    mock_global_session.execute.reset_mock()
    shard_name_2, shard_dsn_2 = await resolver.resolve(tenant_id="1")
    assert shard_name_2 == "ucp_shard_1"
    assert shard_dsn_2 == "postgresql://user:pass@host/db"
    mock_global_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_resolver_not_found() -> None:
    mock_db_router = MagicMock()
    mock_global_session = AsyncMock()
    mock_db_router.get_global_session.return_value = mock_global_session

    class MockEmptyResult:
        def first(self) -> Any:
            return None

    mock_global_session.__anext__.return_value = mock_global_session
    mock_global_session.execute.return_value = MockEmptyResult()

    resolver = TenantResolver(db_router=mock_db_router, ttl_secs=300)

    with pytest.raises(ValueError, match="Tenant 999 not found in Global DB"):
        await resolver.resolve(tenant_id="999")


@pytest.mark.asyncio
async def test_tenant_resolver_eviction() -> None:
    mock_db_router = MagicMock()
    mock_global_session = AsyncMock()
    mock_db_router.get_global_session.return_value = mock_global_session

    class MockRow:
        def __init__(self, name: str, dsn: str) -> None:
            self.name = name
            self.dsn = dsn

    class MockResult:
        def first(self) -> Any:
            return (None, MockRow("ucp_shard_1", "postgresql://user:pass@host/db"))

    mock_global_session.__anext__.return_value = mock_global_session
    mock_global_session.execute.return_value = MockResult()

    # Small cache size to force eviction
    resolver = TenantResolver(db_router=mock_db_router, ttl_secs=300, max_entries=2)

    await resolver.resolve(tenant_id="1")
    await resolver.resolve(tenant_id="2")
    # This should evict tenant 1 or 2
    await resolver.resolve(tenant_id="3")

    assert len(resolver._cache) == 2
