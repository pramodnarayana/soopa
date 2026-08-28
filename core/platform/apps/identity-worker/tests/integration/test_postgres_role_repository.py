import uuid

import pytest
from database.models.identity import Role as OrmRole
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
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

        from database.models.identity import Tenant as OrmTenant

        dummy_tenant = {
            "id": "ten_12345",
            "name": "Test Tenant",
            "slug": "test-tenant",
            "idp_tenant_id": "test_123",
            "status": "active",
            "created_at": datetime.datetime.now().replace(tzinfo=None),
            "updated_at": datetime.datetime.now().replace(tzinfo=None),
        }
        platform_tenant = {
            "id": "ten_000000000000000000000000",
            "name": "Platform Tenant",
            "slug": "platform",
            "idp_tenant_id": "platform",
            "status": "active",
            "created_at": datetime.datetime.now().replace(tzinfo=None),
            "updated_at": datetime.datetime.now().replace(tzinfo=None),
        }
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(OrmTenant)
            .values([dummy_tenant, platform_tenant])
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db_session.execute(stmt)

        # Insert a few global roles (tenant_id IS NULL)
        global_role_1 = {
            "id": f"role_{uuid.uuid4().hex[:12]}",
            "name": "Global Admin Test",
            "description": "Admin for tests",
            "tenant_id": "ten_000000000000000000000000",
            "capabilities": ["test:read", "test:write"],
        }

        global_role_2 = {
            "id": f"role_{uuid.uuid4().hex[:12]}",
            "name": "Global Viewer Test",
            "description": "Viewer for tests",
            "tenant_id": "ten_000000000000000000000000",
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

        await db_session.execute(
            insert(OrmRole).values([global_role_1, global_role_2, tenant_role])
        )

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
        assert fetched_role.tenant_id == "ten_000000000000000000000000"
        assert set(fetched_role.capabilities) == {"test:read", "test:write"}
