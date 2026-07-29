from unittest.mock import AsyncMock

import pytest

from api.core.uow import ControlPlaneUnitOfWork, DataPlaneUnitOfWork


@pytest.mark.asyncio
async def test_control_plane_uow():
    mock_global_session = AsyncMock()
    uow = ControlPlaneUnitOfWork(global_session=mock_global_session)
    async with uow:
        assert uow.global_session == mock_global_session
        assert uow.as2_partners is not None
        await uow.commit()
    mock_global_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_control_plane_uow_rollback():
    mock_global_session = AsyncMock()
    uow = ControlPlaneUnitOfWork(global_session=mock_global_session)
    try:
        async with uow:
            raise ValueError("Test error")
    except ValueError:
        pass
    mock_global_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_data_plane_uow():
    mock_tenant_session = AsyncMock()
    uow = DataPlaneUnitOfWork(tenant_session=mock_tenant_session)
    async with uow:
        assert uow.tenant_session == mock_tenant_session
        assert uow.transactions is not None
        await uow.commit()
    mock_tenant_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_data_plane_uow_rollback():
    mock_tenant_session = AsyncMock()
    uow = DataPlaneUnitOfWork(tenant_session=mock_tenant_session)
    try:
        async with uow:
            raise ValueError("Test error")
    except ValueError:
        pass
    mock_tenant_session.rollback.assert_awaited_once()
