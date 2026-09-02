import pytest
from identity.domain.constants import IdentityIdPrefix
from identity.domain.models.authorization import Role
from identity.domain.models.user import User
from seedwork import generate_id, generate_random_hex
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.dto import AssignUserRoleRequest
from ucp.application.use_cases.roles.assign_user_role_use_case import (
    AssignUserRoleUseCase,
)
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_assign_user_role_integration(db_session: AsyncSession) -> None:
    """
    Narrow integration test for AssignUserRoleUseCase.
    Uses the real PostgreSQL database and actual Repositories to test the full flow.
    """
    uow = SqlAlchemyUcpUnitOfWork(db_session)
    use_case = AssignUserRoleUseCase(uow)

    # 1. Setup Data
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    user_id = generate_id(IdentityIdPrefix.USER)
    role_id = generate_id(IdentityIdPrefix.ROLE)

    # Seed Tenant first (required for foreign key relationship)

    tenant = Tenant.create(
        id=tenant_id,
        name=f"Test Tenant {generate_random_hex(6)}",
        slug=f"test-tenant-{generate_random_hex(6)}",
        idp_tenant_id=None,
    )  # Override generated ID for test consistency
    await uow.tenant_repo.save(tenant)

    # Seed User
    user = User.create(
        id=user_id,
        idp_user_id=None,
        email=f"test_{generate_random_hex(6)}@example.com",
        name="Integration Test User",
    )
    await uow.user_repo.save(user)

    # Seed Role and assign to user — replaces the old TenantUser junction table.
    # find_by_id_and_tenant now joins on identity.user_roles via PBAC.
    seed_role_id = generate_id(IdentityIdPrefix.ROLE)
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

    # Seed Role
    role = Role.create(
        id=role_id,
        tenant_id=tenant_id,
        name=f"Test Role {generate_random_hex(6)}",
        description="A test role",
        capabilities=["users:write"],
    )
    await uow.role_repo.save(role)
    await db_session.flush()

    # 2. Execute Use Case
    request = AssignUserRoleRequest(user_id=user_id, role_id=role_id)
    await use_case.execute(tenant_id=tenant_id, request=request)

    # 3. Verify
    # Check if the role capability is now attached to the user for that tenant
    capabilities = await uow.role_repo.get_user_capabilities(tenant_id, user_id)
    assert "users:write" in capabilities


@pytest.mark.asyncio
async def test_assign_user_role_not_found(db_session: AsyncSession) -> None:
    uow = SqlAlchemyUcpUnitOfWork(db_session)
    use_case = AssignUserRoleUseCase(uow)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    request = AssignUserRoleRequest(user_id="iam_usr_doesnt_exist", role_id="iam_rol_xyz")

    with pytest.raises(ResourceNotFoundError):
        await use_case.execute(tenant_id=tenant_id, request=request)


@pytest.mark.asyncio
async def test_assign_user_role_role_not_found(db_session: AsyncSession) -> None:
    """
    Narrow integration test: assigning a non-existent role_id must raise ResourceNotFoundError.
    The user and tenant exist — only the role is missing.
    """
    uow = SqlAlchemyUcpUnitOfWork(db_session)
    use_case = AssignUserRoleUseCase(uow)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    user_id = generate_id(IdentityIdPrefix.USER)
    role_id = generate_id(IdentityIdPrefix.ROLE)  # never seeded

    tenant = Tenant.create(
        id=tenant_id,
        name=f"Tenant {tenant_id}",
        slug=f"tenant-{tenant_id}",
        idp_tenant_id=None,
    )
    await uow.tenant_repo.save(tenant)

    user = User.create(id=user_id, idp_user_id=None, email=f"{user_id}@test.com", name="Test User")
    await uow.user_repo.save(user)
    # Seed PBAC membership so find_by_id_and_tenant can resolve the user.
    seed_role_id2 = generate_id(IdentityIdPrefix.ROLE)
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

    request = AssignUserRoleRequest(user_id=user_id, role_id=role_id)

    with pytest.raises(ResourceNotFoundError):
        await use_case.execute(tenant_id=tenant_id, request=request)
