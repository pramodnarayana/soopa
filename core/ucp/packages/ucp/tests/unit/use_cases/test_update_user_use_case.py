from datetime import UTC, datetime

import pytest
from identity.domain.constants import UserStatus
from identity.domain.models.authorization import Role
from identity.domain.models.user import User

from ucp.application.use_cases.update_user_use_case import UpdateUserCommand, UpdateUserUseCase
from ucp.domain.constants import LifecycleStatus
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def update_user_use_case(fake_uow):
    return UpdateUserUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_update_user_success(fake_uow, update_user_use_case):
    # Setup Tenant
    tenant = Tenant(
        id="iam_ten_123",
        name="Test Tenant",
        slug="test",
        idp_tenant_id="idp_org_123",
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    # Setup Role
    role = Role(
        id="iam_rol_abc",
        name="admin",
        description="Admin role",
        capabilities=["read", "write"],
        tenant_id=None,
    )
    await fake_uow.role_repo.save(role)

    # Setup User
    user = User(
        id="iam_usr_123",
        email="test@example.com",
        name="Old Name",
        idp_user_id="idp_usr_123",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.user_repo.save(user)

    # Establish fake membership so find_by_id_and_tenant works
    fake_uow.user_repo.tenant_memberships.add(("iam_ten_123", "iam_usr_123"))

    command = UpdateUserCommand(
        tenant_id="iam_ten_123",
        user_id="iam_usr_123",
        first_name="New",
        last_name="Name",
        role="admin",
    )

    await update_user_use_case.execute(command)

    # Verify user was updated
    saved_user = await fake_uow.user_repo.find_by_id("iam_usr_123")
    assert saved_user.name == "New Name"

    # Verify PBAC role was assigned
    role_memberships = fake_uow.role_repo.user_roles
    assert any(
        r[0] == "iam_ten_123" and r[1] == "iam_usr_123" and r[2] == "iam_rol_abc"
        for r in role_memberships
    )

    # Verify domain events
    events = saved_user.domain_events
    # update_profile emits UserUpdatedEvent
    # assign_role emits UserRoleAssignedEvent
    assert len(events) == 2
    assert events[0].__class__.__name__ == "UserUpdatedEvent"
    assert events[1].__class__.__name__ == "UserRoleAssignedEvent"


@pytest.mark.asyncio
async def test_update_user_tenant_not_found(update_user_use_case):
    command = UpdateUserCommand(
        tenant_id="iam_ten_unknown",
        user_id="iam_usr_123",
        first_name="New",
        last_name="Name",
        role="admin",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await update_user_use_case.execute(command)
    assert "Tenant iam_ten_unknown not found" in str(exc.value)


@pytest.mark.asyncio
async def test_update_user_user_not_found(fake_uow, update_user_use_case):
    tenant = Tenant(
        id="iam_ten_123",
        name="Test Tenant",
        slug="test",
        idp_tenant_id="idp_org_123",
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.tenant_repo.save(tenant)

    command = UpdateUserCommand(
        tenant_id="iam_ten_123",
        user_id="iam_usr_unknown",
        first_name="New",
        last_name="Name",
        role="admin",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await update_user_use_case.execute(command)
    assert "User iam_usr_unknown not found" in str(exc.value)
