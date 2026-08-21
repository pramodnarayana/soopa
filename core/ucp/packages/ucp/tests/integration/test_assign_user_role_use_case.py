import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.roles.assign_user_role_use_case import (
    AssignUserRoleRequest,
    AssignUserRoleUseCase,
)
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.authorization import Role
from ucp.domain.models.user import User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_assign_user_role_integration(db_session: AsyncSession) -> None:
    """
    Narrow integration test for AssignUserRoleUseCase.
    Uses the real PostgreSQL database and actual Repositories to test the full flow.
    """
    async with db_session.begin_nested():
        uow = SqlAlchemyUcpUnitOfWork(db_session)
        use_case = AssignUserRoleUseCase(uow)

        # 1. Setup Data
        tenant_id = f"ten_{uuid.uuid4().hex[:12]}"
        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        role_id = f"rol_{uuid.uuid4().hex[:12]}"

        # Seed Tenant first (required for foreign key relationship)
        from ucp.domain.models.tenant import Tenant

        tenant = Tenant.create(
            id=tenant_id,
            name="Test Tenant",
            slug=f"test-tenant-{uuid.uuid4().hex[:8]}",
            idp_tenant_id=None,
        )  # Override generated ID for test consistency
        await uow.tenant_repo.save(tenant)

        # Seed User
        user = User.create(
            id=user_id, idp_user_id=None, email="test@example.com", name="Integration Test User"
        )
        await uow.user_repo.save(user)

        # Seed Role and assign to user — replaces the old TenantUser junction table.
        # find_by_id_and_tenant now joins on identity.user_roles via PBAC.
        seed_role_id = f"rol_{uuid.uuid4().hex[:12]}"
        seed_role = Role.create(
            id=seed_role_id,
            tenant_id=tenant_id,
            name="Viewer",
            description="Seed role for test scaffolding",
            capabilities=["users:read"],
        )
        await uow.role_repo.save(seed_role)
        await db_session.flush()
        await uow.role_repo.assign_user_role(
            tenant_id=tenant_id, user_id=user_id, role_id=seed_role_id
        )

        # Seed Role
        role = Role.create(
            id=role_id,
            tenant_id=tenant_id,
            name="Test Role",
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
    async with db_session.begin_nested():
        uow = SqlAlchemyUcpUnitOfWork(db_session)
        use_case = AssignUserRoleUseCase(uow)

        tenant_id = f"ten_{uuid.uuid4().hex[:12]}"
        request = AssignUserRoleRequest(user_id="usr_doesnt_exist", role_id="rol_xyz")

        with pytest.raises(ResourceNotFoundError):
            await use_case.execute(tenant_id=tenant_id, request=request)


@pytest.mark.asyncio
async def test_assign_user_role_role_not_found(db_session: AsyncSession) -> None:
    """
    Narrow integration test: assigning a non-existent role_id must raise ResourceNotFoundError.
    The user and tenant exist — only the role is missing.
    """
    async with db_session.begin_nested():
        uow = SqlAlchemyUcpUnitOfWork(db_session)
        use_case = AssignUserRoleUseCase(uow)

        tenant_id = f"ten_{uuid.uuid4().hex[:12]}"
        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        role_id = f"rol_{uuid.uuid4().hex[:12]}"  # never seeded

        from ucp.domain.models.tenant import Tenant

        tenant = Tenant.create(
            id=tenant_id,
            name=f"Tenant {tenant_id}",
            slug=f"tenant-{tenant_id}",
            idp_tenant_id=None,
        )
        await uow.tenant_repo.save(tenant)

        user = User.create(
            id=user_id, idp_user_id=None, email=f"{user_id}@test.com", name="Test User"
        )
        await uow.user_repo.save(user)
        # Seed PBAC membership so find_by_id_and_tenant can resolve the user.
        seed_role_id2 = f"rol_{uuid.uuid4().hex[:12]}"
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
