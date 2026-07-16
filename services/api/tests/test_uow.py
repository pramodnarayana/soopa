from unittest.mock import AsyncMock

import pytest
from api.core.uow import UnitOfWork


@pytest.mark.asyncio
async def test_sqlalchemy_uow():
    mock_global_session = AsyncMock()
    mock_tenant_session = AsyncMock()

    uow = UnitOfWork(global_session=mock_global_session, tenant_session=mock_tenant_session)

    async with uow:
        assert uow.global_session == mock_global_session
        assert uow.tenant_session == mock_tenant_session
        assert uow.as2_partners is not None
        assert uow.transactions is not None

        await uow.commit()

    mock_global_session.commit.assert_awaited_once()
    mock_tenant_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sqlalchemy_uow_rollback():
    mock_global_session = AsyncMock()
    mock_tenant_session = AsyncMock()

    uow = UnitOfWork(global_session=mock_global_session, tenant_session=mock_tenant_session)

    try:
        async with uow:
            await uow.rollback()
            raise ValueError("Test error")
    except ValueError:
        pass

    mock_global_session.rollback.assert_awaited()
    mock_tenant_session.rollback.assert_awaited()
