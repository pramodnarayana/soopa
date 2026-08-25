import uuid

import pytest
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from platform_orm.models.identity import Role as OrmRole
from sqlalchemy import insert

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_role_repository_get_global_roles(db_session_factory) -> None:
    """
    Narrow integration test for PostgresRoleRepository.get_global_roles.
    """
    async with db_session_factory() as db_session:
        async with db_session.begin_nested():
            repo = PostgresRoleRepository(db_session)

        import datetime

        from platform_orm.models.identity import Tenant as OrmTenant

        tenant_id = "ten_12345"
        dummy_tenant = {
            "id": tenant_id,
            "name": "Test Tenant",
            "slug": "test-tenant",
            "idp_tenant_id": "test_123",
            "status": "active",
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
        }
        await db_session.execute(insert(OrmTenant).values([dummy_tenant]))

        # Insert a few global roles (tenant_id IS NULL)
        global_role_1 = {
            "id": f"role_{uuid.uuid4().hex[:12]}",
            "name": "Global Admin Test",
            "description": "Admin for tests",
            "tenant_id": None,
            "capabilities": ["test:read", "test:write"],
        }

        global_role_2 = {
            "id": f"role_{uuid.uuid4().hex[:12]}",
            "name": "Global Viewer Test",
            "description": "Viewer for tests",
            "tenant_id": None,
            "capabilities": ["test:read"],
        }

        # Insert a tenant role (tenant_id IS NOT NULL) to ensure it is NOT fetched
        tenant_role = {
            "id": f"role_{uuid.uuid4().hex[:12]}",
            "name": "Tenant Admin Test",
            "description": "Tenant Admin for tests",
            "tenant_id": "ten_12345",
            "capabilities": ["test:read", "test:write"],
        }

        await db_session.execute(insert(OrmRole).values([global_role_1, global_role_2, tenant_role]))

        # Fetch global roles
        roles = await repo.get_global_roles()

        # Verify the two global roles are fetched and the tenant one is not
        role_ids = {r.id for r in roles}
        assert global_role_1["id"] in role_ids
        assert global_role_2["id"] in role_ids
        assert tenant_role["id"] not in role_ids

        # Verify mapping
        fetched_role = next(r for r in roles if r.id == global_role_1["id"])
        assert fetched_role.name == "Global Admin Test"
        assert fetched_role.tenant_id is None
        assert set(fetched_role.capabilities) == {"test:read", "test:write"}
