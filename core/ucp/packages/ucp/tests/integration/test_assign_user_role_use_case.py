import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.roles.assign_user_role_use_case import (
    AssignUserRoleRequest,
    AssignUserRoleUseCase,
)
from ucp.core.exceptions import ResourceNotFoundError
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

        # Seed User
        user = User.create(
            id=user_id, idp_user_id=None, email="test@example.com", name="Integration Test User"
        )
        await uow.user_repo.save(user)
        # We need a TenantUser relationship to allow find_by_id_and_tenant to work
        await uow.user_repo.save_tenant_membership(
            tenant_id=tenant_id, user_id=user.id, role="viewer"
        )

        # Seed Role
        role = Role.create(
            id=role_id,
            tenant_id=tenant_id,
            name="Test Role",
            description="A test role",
            capabilities=["users:read"],
        )
        await uow.role_repo.save(role)
        await db_session.flush()

        # 2. Execute Use Case
        request = AssignUserRoleRequest(user_id=user_id, role_id=role_id)
        await use_case.execute(tenant_id=tenant_id, request=request)

        # 3. Verify
        # Check if the role capability is now attached to the user for that tenant
        capabilities = await uow.role_repo.get_user_capabilities(tenant_id, user_id)
        assert "users:read" in capabilities


@pytest.mark.asyncio
async def test_assign_user_role_not_found(db_session: AsyncSession) -> None:
    async with db_session.begin_nested():
        uow = SqlAlchemyUcpUnitOfWork(db_session)
        use_case = AssignUserRoleUseCase(uow)

        tenant_id = f"ten_{uuid.uuid4().hex[:12]}"
        request = AssignUserRoleRequest(user_id="usr_doesnt_exist", role_id="rol_xyz")

        with pytest.raises(ResourceNotFoundError):
            await use_case.execute(tenant_id=tenant_id, request=request)
