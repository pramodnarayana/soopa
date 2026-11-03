import pytest
from identity.domain.authorization import Capability
from seedwork.utils import generate_id

from ucp.application.use_cases.roles.create_role_use_case import (
    CreateRoleCommand,
    CreateRoleUseCase,
)
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def use_case(fake_uow: FakeUcpUnitOfWork) -> CreateRoleUseCase:
    return CreateRoleUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_create_role_success(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    request = CreateRoleCommand(
        name="Custom Role",
        description="A role with read access.",
        capabilities=(Capability.INVOICES_READ.value, Capability.USERS_READ.value),
    )

    res = await use_case.execute(tenant_id=tenant_id, request=request)

    assert res.is_ok
    response = res.unwrap()
    assert response.name == "Custom Role"
    assert response.capabilities == list(request.capabilities)

    assert len(fake_uow.role_repo.roles) == 1
    saved_role = fake_uow.role_repo.roles[0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == list(request.capabilities)
    assert saved_role.tenant_id == tenant_id
    assert fake_uow.committed is True


@pytest.mark.asyncio
async def test_create_role_invalid_capability(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    request = CreateRoleCommand(
        name="Custom Role",
        capabilities=("invalid:capability",),
    )

    res = await use_case.execute(tenant_id=tenant_id, request=request)

    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.INVALID_CAPABILITY
    assert "Invalid capability: invalid:capability" in err.message
    assert len(fake_uow.role_repo.roles) == 0
    assert fake_uow.committed is False


@pytest.mark.asyncio
async def test_create_platform_role_success(
    use_case: CreateRoleUseCase, fake_uow: FakeUcpUnitOfWork
) -> None:
    request = CreateRoleCommand(
        name="Platform Auditor",
        description="Global auditor with read access to tenants.",
        capabilities=(Capability.PLATFORM_ADMIN.value,),
    )

    res = await use_case.execute(tenant_id=None, request=request)

    assert res.is_ok
    response = res.unwrap()
    assert response.name == "Platform Auditor"
    assert response.capabilities == list(request.capabilities)

    assert len(fake_uow.role_repo.roles) == 1
    saved_role = fake_uow.role_repo.roles[0]
    assert saved_role.name == request.name
    assert saved_role.capabilities == list(request.capabilities)
    assert saved_role.tenant_id is None
    assert fake_uow.committed is True
