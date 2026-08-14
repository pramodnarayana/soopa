from unittest.mock import create_autospec

import pytest

from ucp.application.use_cases.roles.create_role_use_case import (
    CreateRoleRequest,
    CreateRoleUseCase,
)
from ucp.core.exceptions import InvalidCapabilityError
from ucp.domain.models.authorization import Capability
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
def use_case(mock_uow: UcpUnitOfWorkPort) -> CreateRoleUseCase:
    return CreateRoleUseCase(uow=mock_uow)


@pytest.mark.asyncio
async def test_create_role_success(use_case: CreateRoleUseCase, mock_uow: UcpUnitOfWorkPort):
    # Arrange
    tenant_id = "ten_123"
    request = CreateRoleRequest(
        name="Custom Role",
        description="A role with read access.",
        capabilities=[Capability.INVOICES_READ.value, Capability.USERS_READ.value],
    )

    # Act
    response = await use_case.execute(tenant_id=tenant_id, request=request)

    # Assert
    assert response.name == "Custom Role"
    assert response.capabilities == request.capabilities

    mock_uow.role_repo.save.assert_awaited_once()
    saved_role = mock_uow.role_repo.save.call_args[0][0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == request.capabilities
    assert saved_role.tenant_id == tenant_id

    # Verify Transaction commit
    mock_uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_role_invalid_capability(
    use_case: CreateRoleUseCase, mock_uow: UcpUnitOfWorkPort
):
    # Arrange
    tenant_id = "ten_123"
    request = CreateRoleRequest(
        name="Custom Role",
        capabilities=["invalid:capability"],
    )

    # Act & Assert
    with pytest.raises(InvalidCapabilityError, match="Invalid capability: invalid:capability"):
        await use_case.execute(tenant_id=tenant_id, request=request)

    # Verify no database mutations were attempted
    mock_uow.role_repo.save.assert_not_called()
    mock_uow.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_platform_role_success(
    use_case: CreateRoleUseCase, mock_uow: UcpUnitOfWorkPort
):
    # Arrange
    tenant_id = None
    request = CreateRoleRequest(
        name="Platform Auditor",
        description="Global auditor with read access to tenants.",
        capabilities=[Capability.PLATFORM_ADMIN.value],
    )

    # Act
    response = await use_case.execute(tenant_id=tenant_id, request=request)

    # Assert
    assert response.name == "Platform Auditor"
    assert response.capabilities == request.capabilities

    mock_uow.role_repo.save.assert_awaited_once()
    saved_role = mock_uow.role_repo.save.call_args[0][0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == request.capabilities
    assert saved_role.tenant_id == tenant_id

    # Verify Transaction commit
    mock_uow.commit.assert_awaited_once()
