import pytest
from identity.domain.constants import IdentityIdPrefix
from identity.domain.models.authorization import Capability
from seedwork.utils import generate_id

from ucp.application.dto import CreateRoleRequest
from ucp.application.use_cases.roles.create_role_use_case import CreateRoleUseCase
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
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    request = CreateRoleRequest(
        name="Custom Role",
        description="A role with read access.",
        capabilities=[Capability.INVOICES_READ.value, Capability.USERS_READ.value],
    )

    response = await use_case.execute(tenant_id=tenant_id, request=request)

    assert response.name == "Custom Role"
    assert response.capabilities == request.capabilities

    assert len(fake_uow.role_repo.roles) == 1
    saved_role = fake_uow.role_repo.roles[0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == request.capabilities
    assert saved_role.tenant_id == tenant_id
    assert fake_uow.committed is True


@pytest.mark.asyncio
async def test_create_role_invalid_capability(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
):
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    request = CreateRoleRequest(
        name="Custom Role",
        capabilities=["invalid:capability"],
    )

    with pytest.raises(InvalidCapabilityError, match="Invalid capability: invalid:capability"):
        await use_case.execute(tenant_id=tenant_id, request=request)

    assert len(fake_uow.role_repo.roles) == 0
    assert fake_uow.committed is False


@pytest.mark.asyncio
async def test_create_platform_role_success(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
):
    request = CreateRoleRequest(
        name="Platform Auditor",
        description="Global auditor with read access to tenants.",
        capabilities=[Capability.PLATFORM_ADMIN.value],
    )

    response = await use_case.execute(tenant_id=None, request=request)

    assert response.name == "Platform Auditor"
    assert response.capabilities == request.capabilities

    assert len(fake_uow.role_repo.roles) == 1
    saved_role = fake_uow.role_repo.roles[0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == request.capabilities
    assert saved_role.tenant_id is None
    assert fake_uow.committed is True
