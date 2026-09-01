from datetime import UTC, datetime

import pytest
from identity.domain.constants import IdentityIdPrefix
from identity.domain.models.authorization import Role
from seedwork.utils import generate_id

from ucp.application.use_cases.create_user_use_case import CreateUserCommand, CreateUserUseCase
from ucp.domain.constants import LifecycleStatus
from ucp.domain.exceptions import ResourceNotFoundError, StateConflictError
from ucp.domain.models.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def create_user_use_case(fake_uow):
    return CreateUserUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_create_user_success(fake_uow, create_user_use_case):
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    role_id = generate_id(IdentityIdPrefix.ROLE)

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
        tenant_id=None,
    )
    await fake_uow.role_repo.save(role)

    command = CreateUserCommand(
        tenant_id=tenant_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="admin",
    )

    user_id = await create_user_use_case.execute(command)

    assert user_id.startswith("iam_usr_")

    saved_user = await fake_uow.user_repo.find_by_id(user_id)
    assert saved_user is not None
    assert saved_user.email == "test@example.com"
    assert saved_user.name == "Test User"

    role_memberships = fake_uow.role_repo.user_roles
    assert any(r[0] == tenant_id and r[1] == user_id and r[2] == role_id for r in role_memberships)

    events = saved_user.domain_events
    assert len(events) == 2
    assert events[1].__class__.__name__ == "UserCreatedEvent"
    assert events[1].email == "test@example.com"


@pytest.mark.asyncio
async def test_create_user_tenant_not_found(create_user_use_case):
    unknown_tenant_id = generate_id(IdentityIdPrefix.TENANT)
    command = CreateUserCommand(
        tenant_id=unknown_tenant_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="admin",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await create_user_use_case.execute(command)
    assert unknown_tenant_id in str(exc.value)
    assert "not found" in str(exc.value)


@pytest.mark.asyncio
async def test_create_user_no_idp_tenant(fake_uow, create_user_use_case):
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
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
        role="admin",
    )

    with pytest.raises(StateConflictError) as exc:
        await create_user_use_case.execute(command)
    assert "has no associated IDP organization" in str(exc.value)


@pytest.mark.asyncio
async def test_create_user_role_not_found(fake_uow, create_user_use_case):
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
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
        role="unknown_role",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await create_user_use_case.execute(command)
    assert "not found in the database" in str(exc.value)
