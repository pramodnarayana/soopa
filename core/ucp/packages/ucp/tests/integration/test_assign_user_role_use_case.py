import pytest
from identity.domain.authorization import Role
from identity.domain.user import User
from seedwork import generate_id, generate_random_hex
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.application.use_cases.roles.assign_user_role_use_case import (
    AssignUserRoleCommand,
    AssignUserRoleUseCase,
)
from ucp.bootstrap.container import create_ucp_uow
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.domain.tenant import Tenant

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_assign_user_role_integration(db_session: AsyncSession) -> None:
    """
    Narrow integration test for AssignUserRoleUseCase.
    Uses the real PostgreSQL database and actual Repositories to test the full flow.
    """
    uow = create_ucp_uow(db_session)
    use_case = AssignUserRoleUseCase(uow)

    tenant_id = generate_id(DomainIdPrefix.TENANT)
    user_id = generate_id(DomainIdPrefix.USER)
    role_id = generate_id(DomainIdPrefix.ROLE)

    tenant = Tenant.create(
        id=tenant_id,
        name=f"Test Tenant {generate_random_hex(6)}",
        slug=f"test-tenant-{generate_random_hex(6)}",
        idp_tenant_id=None,
    ).unwrap()
    await uow.tenant_repo.save(tenant)

    user = User.create(
        id=user_id,
        idp_user_id=None,
        email=f"test_{generate_random_hex(6)}@example.com",
        name="Integration Test User",
    ).unwrap()
    await uow.user_repo.save(user)

    seed_role_id = generate_id(DomainIdPrefix.ROLE)
    seed_role = Role.create(
        id=seed_role_id,
        tenant_id=tenant_id,
        name="Viewer",
        description="Seed role for test scaffolding",
        capabilities=["users:read"],
    )
    await uow.role_repo.save(seed_role)
    await db_session.flush()
    await uow.role_repo.assign_user_role(tenant_id=tenant_id, user_id=user_id, role_id=seed_role_id)

    role = Role.create(
        id=role_id,
        tenant_id=tenant_id,
        name=f"Test Role {generate_random_hex(6)}",
        description="A test role",
        capabilities=["users:write"],
    )
    await uow.role_repo.save(role)
    await db_session.flush()

    request = AssignUserRoleCommand(user_id=user_id, role_id=role_id)
    res = await use_case.execute(tenant_id=tenant_id, request=request)
    assert res.is_ok

    capabilities = await uow.role_repo.get_user_capabilities(tenant_id, user_id)
    assert "users:write" in capabilities


@pytest.mark.asyncio
async def test_assign_user_role_not_found(db_session: AsyncSession) -> None:
    uow = create_ucp_uow(db_session)
    use_case = AssignUserRoleUseCase(uow)

    tenant_id = generate_id(DomainIdPrefix.TENANT)
    request = AssignUserRoleCommand(
        user_id=generate_id(DomainIdPrefix.USER),
        role_id=generate_id(DomainIdPrefix.ROLE),
    )

    res = await use_case.execute(tenant_id=tenant_id, request=request)
    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.USER_NOT_FOUND


@pytest.mark.asyncio
async def test_assign_user_role_role_not_found(db_session: AsyncSession) -> None:
    """
    Narrow integration test: assigning a non-existent role_id must return ROLE_NOT_FOUND.
    The user and tenant exist — only the role is missing.
    """
    uow = create_ucp_uow(db_session)
    use_case = AssignUserRoleUseCase(uow)

    tenant_id = generate_id(DomainIdPrefix.TENANT)
    user_id = generate_id(DomainIdPrefix.USER)
    role_id = generate_id(DomainIdPrefix.ROLE)

    tenant = Tenant.create(
        id=tenant_id,
        name=f"Tenant {tenant_id}",
        slug=f"tenant-{tenant_id}",
        idp_tenant_id=None,
    ).unwrap()
    await uow.tenant_repo.save(tenant)

    user = User.create(
        id=user_id, idp_user_id=None, email=f"{user_id}@test.com", name="Test User"
    ).unwrap()
    await uow.user_repo.save(user)

    seed_role_id2 = generate_id(DomainIdPrefix.ROLE)
    seed_role2 = Role.create(
        id=seed_role_id2,
        tenant_id=tenant_id,
        name="Viewer",
        description="Seed role for test scaffolding",
        capabilities=["users:read"],
    )
    await uow.role_repo.save(seed_role2)
    await db_session.flush()
    await uow.role_repo.assign_user_role(
        tenant_id=tenant_id, user_id=user_id, role_id=seed_role_id2
    )
    await db_session.flush()

    request = AssignUserRoleCommand(user_id=user_id, role_id=role_id)

    res = await use_case.execute(tenant_id=tenant_id, request=request)
    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.ROLE_NOT_FOUND
