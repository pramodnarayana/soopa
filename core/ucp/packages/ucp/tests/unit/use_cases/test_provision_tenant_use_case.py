from datetime import UTC, datetime

import pytest
from identity.domain.constants import UserStatus
from identity.domain.models.authorization import Role
from identity.domain.models.user import User

from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    uow = FakeUcpUnitOfWork()

    # Pre-populate global role
    tenant_admin_role = Role(
        id="rol_tenant_admin_123",
        tenant_id=None,
        name="Tenant Admin",
        description="Tenant Admin Role",
        capabilities=["tenant:admin"],
    )
    uow.role_repo.roles.append(tenant_admin_role)

    # Pre-populate user
    user = User(
        id="usr_creator_123",
        idp_user_id="idp_creator_123",
        email="creator@example.com",
        name="Creator",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    uow.user_repo.users.append(user)

    return uow


@pytest.fixture
def provision_use_case(
    fake_uow: FakeUcpUnitOfWork,
) -> ProvisionTenantUseCase:
    return ProvisionTenantUseCase(
        uow=fake_uow,
    )


@pytest.mark.asyncio
async def test_provision_tenant_success(
    provision_use_case: ProvisionTenantUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    # Arrange
    command = ProvisionTenantCommand(name="Test Tenant", creator_id="usr_creator_123")

    # Act
    tenant = await provision_use_case.execute(command, idempotency_key="idemp-1")

    # Assert - correct calls to the ports
    assert len(fake_uow.tenant_repo.saved_tenants) == 1

    # Assert — the tenant passed to save is correct
    saved_tenant = fake_uow.tenant_repo.saved_tenants[0]
    assert saved_tenant.name == "Test Tenant"
    assert saved_tenant.idp_tenant_id is None
    assert saved_tenant.id.startswith("ten_")

    # Assert — the returned tenant is the same object persisted
    assert tenant is saved_tenant

    # Assert — a provisioned domain event was raised
    assert len(tenant.domain_events) == 1
    assert tenant.domain_events[0].tenant_id == tenant.id
    assert tenant.domain_events[0].tenant_name == "Test Tenant"
