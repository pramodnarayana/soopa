from datetime import UTC, datetime

import pytest
from identity.domain.authorization import Role
from identity.domain.constants import UserStatus
from identity.domain.user import User
from seedwork.utils import generate_id

from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.domain.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    uow = FakeUcpUnitOfWork()

    tenant_admin_role = Role(
        id=generate_id(DomainIdPrefix.ROLE),
        tenant_id=None,
        name="Tenant Admin",
        description="Tenant Admin Role",
        capabilities=["tenant:admin"],
    )
    uow.role_repo.roles.append(tenant_admin_role)

    user = User(
        id=generate_id(DomainIdPrefix.USER),
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
    return ProvisionTenantUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_provision_tenant_success(
    provision_use_case: ProvisionTenantUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = ProvisionTenantCommand(name="Test Tenant")

    res = await provision_use_case.execute(command, idempotency_key="idemp-1")

    assert res.is_ok
    tenant = res.unwrap()
    assert len(fake_uow.tenant_repo.saved_tenants) == 1

    saved_tenant = fake_uow.tenant_repo.saved_tenants[0]
    assert saved_tenant.name == "Test Tenant"
    assert saved_tenant.idp_tenant_id is None
    assert saved_tenant.id.startswith("iam_ten_")
    assert tenant is saved_tenant

    assert len(tenant.domain_events) == 1
    assert tenant.domain_events[0].tenant_id == tenant.id


@pytest.mark.asyncio
async def test_provision_tenant_invalid_name_returns_error(
    provision_use_case: ProvisionTenantUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = ProvisionTenantCommand(name="!!!")

    res = await provision_use_case.execute(command)

    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.INVALID_TENANT_NAME
    assert len(fake_uow.tenant_repo.saved_tenants) == 0


@pytest.mark.asyncio
async def test_provision_tenant_retries_on_slug_collision_and_exhausts_cleanly(
    provision_use_case: ProvisionTenantUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    existing = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT),
        name="Acme, Corp.",
        slug="acme-corp",
        idp_tenant_id=None,
    ).unwrap()
    await fake_uow.tenant_repo.save(existing)

    res = await provision_use_case.execute(ProvisionTenantCommand(name="Acme Corp"))
    assert res.is_ok
    created = res.unwrap()
    assert created.slug == "acme-corp-2"

    for suffix in range(3, 11):
        occupied = Tenant.create(
            id=generate_id(DomainIdPrefix.TENANT),
            name=f"Acme Corp Variant {suffix}",
            slug=f"acme-corp-{suffix}",
            idp_tenant_id=None,
        ).unwrap()
        await fake_uow.tenant_repo.save(occupied)

    exhausted = await provision_use_case.execute(ProvisionTenantCommand(name="Acme Corp."))
    assert exhausted.is_err
    assert exhausted.unwrap_err().code == UcpErrorCode.SLUG_EXHAUSTED
