from datetime import UTC, datetime

import pytest
from identity.domain.authorization import Role
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.utils import generate_id

from ucp.application.use_cases.create_user_use_case import CreateUserCommand, CreateUserUseCase
from ucp.domain.constants import LifecycleStatus
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.domain.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def create_user_use_case(fake_uow: FakeUcpUnitOfWork) -> CreateUserUseCase:
    return CreateUserUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_create_user_success(
    fake_uow: FakeUcpUnitOfWork, create_user_use_case: CreateUserUseCase
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    role_id = generate_id(DomainIdPrefix.ROLE)

    tenant = Tenant(
        id=tenant_id,
        name="Test Tenant",
        slug="test",
        idp_tenant_id="idp_org_123",
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    role = Role(
        id=role_id,
        name="admin",
        description="Admin role",
        capabilities=["read", "write"],
        tenant_id=PLATFORM_TENANT_ID,
    )
    await fake_uow.role_repo.save(role)

    command = CreateUserCommand(
        tenant_id=tenant_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role=role_id,
    )

    res = await create_user_use_case.execute(command)

    assert res.is_ok
    user_id = res.unwrap()
    assert user_id.startswith("iam_usr_")

    saved_user = await fake_uow.user_repo.find_by_id(user_id)
    assert saved_user is not None
    assert saved_user.email == "test@example.com"
    assert saved_user.name == "Test User"

    role_memberships = fake_uow.role_repo.user_roles
    assert any(r[0] == tenant_id and r[1] == user_id and r[2] == role_id for r in role_memberships)

    events = saved_user.domain_events
    assert len(events) == 1
    assert events[0].__class__.__name__ == "UserCreatedEvent"


@pytest.mark.asyncio
async def test_create_user_tenant_not_found(create_user_use_case: CreateUserUseCase) -> None:
    unknown_tenant_id = generate_id(DomainIdPrefix.TENANT)
    command = CreateUserCommand(
        tenant_id=unknown_tenant_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role=generate_id(DomainIdPrefix.ROLE),
    )

    res = await create_user_use_case.execute(command)
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.TENANT_NOT_FOUND
    assert unknown_tenant_id in err.message


@pytest.mark.asyncio
async def test_create_user_no_idp_tenant(
    fake_uow: FakeUcpUnitOfWork, create_user_use_case: CreateUserUseCase
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    tenant = Tenant(
        id=tenant_id,
        name="Test Tenant",
        slug="test",
        idp_tenant_id=None,
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    command = CreateUserCommand(
        tenant_id=tenant_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role=generate_id(DomainIdPrefix.ROLE),
    )

    res = await create_user_use_case.execute(command)
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.MISSING_IDP_ORGANIZATION
    assert "has no associated IDP organization" in err.message


@pytest.mark.asyncio
async def test_create_user_role_not_found(
    fake_uow: FakeUcpUnitOfWork, create_user_use_case: CreateUserUseCase
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    tenant = Tenant(
        id=tenant_id,
        name="Test Tenant",
        slug="test",
        idp_tenant_id="idp_org_123",
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    command = CreateUserCommand(
        tenant_id=tenant_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role=generate_id(DomainIdPrefix.ROLE),
    )

    res = await create_user_use_case.execute(command)
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.ROLE_NOT_FOUND
    assert "not found in the database" in err.message
