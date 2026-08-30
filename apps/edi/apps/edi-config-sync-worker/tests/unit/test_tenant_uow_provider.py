from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from edi.adapters.outbound.database.tenant_uow_provider import TenantUowProvider
from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyDataPlaneUnitOfWork,
)

pytestmark = pytest.mark.asyncio


async def test_tenant_uow_provider_success() -> None:
    """Test that TenantUowProvider resolves tenant and yields a DataPlaneUnitOfWorkPort."""
    mock_resolver = AsyncMock()
    mock_resolver.resolve.return_value = ("ucp_shard_2", "postgresql+asyncpg://fake")

    mock_db_router = MagicMock()
    mock_session = AsyncMock()

    # Mock get_tenant_session to return an async generator that yields our mock session
    async def mock_session_gen(*args: object, **kwargs: object) -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    mock_db_router.get_tenant_session.side_effect = mock_session_gen

    mock_settings = MagicMock()

    provider = TenantUowProvider(
        resolver=mock_resolver,
        db_router=mock_db_router,
        settings=mock_settings,
        s3_bucket="fake-bucket",
        aws_endpoint=None,
    )

    uow_factory = await provider.get_uow_factory("tenant_abc")

    # verify resolver was called
    mock_resolver.resolve.assert_called_once_with("tenant_abc")

    # execute the uow_factory
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyDataPlaneUnitOfWork)

    # verify the db router was called with correct parameters
    mock_db_router.get_tenant_session.assert_called_once_with(
        "tenant_abc", "ucp_shard_2", "postgresql+asyncpg://fake"
    )
