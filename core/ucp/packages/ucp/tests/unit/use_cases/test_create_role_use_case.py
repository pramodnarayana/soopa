import pytest
from identity.domain.models.authorization import Capability

from ucp.application.dto import CreateRoleRequest
from ucp.application.use_cases.roles.create_role_use_case import (
    CreateRoleUseCase,
)
from ucp.domain.exceptions import InvalidCapabilityError
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def use_case(fake_uow: FakeUcpUnitOfWork) -> CreateRoleUseCase:
    return CreateRoleUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_create_role_success(use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork):
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

    assert len(fake_uow.role_repo.roles) == 1
    saved_role = fake_uow.role_repo.roles[0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == request.capabilities
    assert saved_role.tenant_id == tenant_id

    # Verify Transaction commit
    assert fake_uow.committed is True


@pytest.mark.asyncio
async def test_create_role_invalid_capability(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
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
    assert len(fake_uow.role_repo.roles) == 0
    assert fake_uow.committed is False


@pytest.mark.asyncio
async def test_create_platform_role_success(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
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

    assert len(fake_uow.role_repo.roles) == 1
    saved_role = fake_uow.role_repo.roles[0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == request.capabilities
    assert saved_role.tenant_id == tenant_id

    # Verify Transaction commit
    assert fake_uow.committed is True
