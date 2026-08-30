from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from identity.domain.models.authorization import Role

from ucp.application.use_cases.create_user_use_case import CreateUserCommand, CreateUserUseCase
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
    # Setup Tenant
    tenant = Tenant(
        id="ten_123",
        name="Test Tenant",
        slug="test",
        idp_tenant_id="idp_org_123",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    # Setup Role
    role = Role(
        id="rol_abc",
        name="admin",
        description="Admin role",
        capabilities=["read", "write"],
        tenant_id=None,
    )
    await fake_uow.role_repo.save(role)

    command = CreateUserCommand(
        tenant_id="ten_123",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="admin",
    )

    with patch("os.urandom") as mock_urandom:
        mock_urandom.return_value = b"random123456"
        user_id = await create_user_use_case.execute(command)

    assert user_id.startswith("usr_")

    # Verify user was saved
    saved_user = await fake_uow.user_repo.find_by_id(user_id)
    assert saved_user is not None
    assert saved_user.email == "test@example.com"
    assert saved_user.name == "Test User"

    # Verify PBAC role was assigned
    role_memberships = fake_uow.role_repo.user_roles
    assert any(
        r[0] == "ten_123" and r[1] == user_id and r[2] == "rol_abc" for r in role_memberships
    )

    # Verify domain events
    events = saved_user.domain_events
    assert len(events) == 2
    assert events[1].__class__.__name__ == "UserCreatedEvent"
    assert events[1].email == "test@example.com"


@pytest.mark.asyncio
async def test_create_user_tenant_not_found(create_user_use_case):
    command = CreateUserCommand(
        tenant_id="ten_unknown",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="admin",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await create_user_use_case.execute(command)
    assert "Tenant ten_unknown not found" in str(exc.value)


@pytest.mark.asyncio
async def test_create_user_no_idp_tenant(fake_uow, create_user_use_case):
    # Setup Tenant with NO idp_tenant_id
    tenant = Tenant(
        id="ten_123",
        name="Test Tenant",
        slug="test",
        idp_tenant_id=None,
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    command = CreateUserCommand(
        tenant_id="ten_123",
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
    tenant = Tenant(
        id="ten_123",
        name="Test Tenant",
        slug="test",
        idp_tenant_id="idp_org_123",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    command = CreateUserCommand(
        tenant_id="ten_123",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="unknown_role",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await create_user_use_case.execute(command)
    assert "not found in the database" in str(exc.value)
