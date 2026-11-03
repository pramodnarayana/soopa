from datetime import UTC, datetime

import pytest
from identity.domain.authorization import Role
from identity.domain.constants import UserStatus
from identity.domain.user import User
from seedwork.utils import generate_id

from ucp.application.use_cases.update_user_use_case import UpdateUserCommand, UpdateUserUseCase
from ucp.domain.constants import LifecycleStatus
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.domain.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def update_user_use_case(fake_uow: FakeUcpUnitOfWork) -> UpdateUserUseCase:
    return UpdateUserUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_update_user_success(
    fake_uow: FakeUcpUnitOfWork, update_user_use_case: UpdateUserUseCase
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    role_id = generate_id(DomainIdPrefix.ROLE)
    user_id = generate_id(DomainIdPrefix.USER)

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

    user = User(
        id=user_id,
        email="test@example.com",
        name="Old Name",
        idp_user_id="idp_usr_123",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.user_repo.save(user)
    fake_uow.user_repo.tenant_memberships.add((tenant_id, user_id))

    command = UpdateUserCommand(
        tenant_id=tenant_id,
        user_id=user_id,
        first_name="New",
        last_name="Name",
        role=role_id,
    )

    res = await update_user_use_case.execute(command)
    assert res.is_ok

    saved_user = await fake_uow.user_repo.find_by_id(user_id)
    assert saved_user is not None
    assert saved_user.name == "New Name"

    role_memberships = fake_uow.role_repo.user_roles
    assert any(r[0] == tenant_id and r[1] == user_id and r[2] == role_id for r in role_memberships)

    events = saved_user.domain_events
    assert len(events) == 2
    assert events[0].__class__.__name__ == "UserUpdatedEvent"
    assert events[1].__class__.__name__ == "UserRoleAssignedEvent"


@pytest.mark.asyncio
async def test_update_user_tenant_not_found(update_user_use_case: UpdateUserUseCase) -> None:
    missing_tenant_id = generate_id(DomainIdPrefix.TENANT)
    command = UpdateUserCommand(
        tenant_id=missing_tenant_id,
        user_id=generate_id(DomainIdPrefix.USER),
        first_name="New",
        last_name="Name",
        role=generate_id(DomainIdPrefix.ROLE),
    )

    res = await update_user_use_case.execute(command)
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.TENANT_NOT_FOUND
    assert missing_tenant_id in err.message


@pytest.mark.asyncio
async def test_update_user_user_not_found(
    fake_uow: FakeUcpUnitOfWork, update_user_use_case: UpdateUserUseCase
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    missing_user_id = generate_id(DomainIdPrefix.USER)
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

    command = UpdateUserCommand(
        tenant_id=tenant_id,
        user_id=missing_user_id,
        first_name="New",
        last_name="Name",
        role=generate_id(DomainIdPrefix.ROLE),
    )

    res = await update_user_use_case.execute(command)
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.USER_NOT_FOUND
    assert missing_user_id in err.message
