from unittest.mock import AsyncMock, create_autospec

import pytest

from ucp.application.use_cases.roles.assign_user_role_use_case import (
    AssignUserRoleRequest,
    AssignUserRoleUseCase,
)
from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.outbound.role_repository import IRoleRepository
from ucp.ports.uow import UcpUnitOfWorkPort


@pytest.fixture
def mock_role_repo() -> IRoleRepository:
    return create_autospec(IRoleRepository, instance=True)


@pytest.fixture
def mock_uow(mock_role_repo: IRoleRepository) -> UcpUnitOfWorkPort:
    uow = create_autospec(UcpUnitOfWorkPort, instance=True)
    uow.role_repo = mock_role_repo
    # Make UoW work as an async context manager
    uow.__aenter__.return_value = uow
    return uow


@pytest.fixture
def use_case(mock_uow: UcpUnitOfWorkPort) -> AssignUserRoleUseCase:
    return AssignUserRoleUseCase(uow=mock_uow)


@pytest.mark.asyncio
async def test_assign_user_role_success(
    use_case: AssignUserRoleUseCase, mock_uow: UcpUnitOfWorkPort
):
    # Arrange
    tenant_id = "ten_123"
    request = AssignUserRoleRequest(
        user_id="usr_abc",
        role_id="rol_xyz",
    )

    mock_uow.role_repo.assign_user_role.return_value = None

    # Act
    await use_case.execute(tenant_id=tenant_id, request=request)

    # Assert
    mock_uow.role_repo.assign_user_role.assert_awaited_once_with(
        tenant_id=tenant_id,
        user_id=request.user_id,
        role_id=request.role_id,
    )

    # Verify Transaction commit
    mock_uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_user_role_resource_not_found(
    use_case: AssignUserRoleUseCase, mock_uow: UcpUnitOfWorkPort
):
    # Arrange
    tenant_id = "ten_123"
    request = AssignUserRoleRequest(
        user_id="usr_nonexistent",
        role_id="rol_xyz",
    )

    # Mock the repository to raise ResourceNotFoundError
    mock_uow.role_repo.assign_user_role.side_effect = ResourceNotFoundError(
        "User 'usr_nonexistent' not found."
    )

    # Act & Assert
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await use_case.execute(tenant_id=tenant_id, request=request)

    assert "not found" in str(exc_info.value).lower()

    # Verify commit was NOT called
    mock_uow.commit.assert_not_awaited()
