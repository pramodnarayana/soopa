import datetime

import pytest
from database.models.identity import Tenant as OrmTenant
from database.models.identity import User as OrmUser
from seedwork import generate_id, generate_random_hex
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ucp.domain.exceptions import IdempotencyConflictError, ResourceNotFoundError

from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.models.authorization import Role as DomainRole

pytestmark = pytest.mark.integration


async def _setup_data(db_session):
    test_tenant_id = generate_id("ten")
    test_user_id = generate_id("usr")
    platform_tenant_id = PLATFORM_TENANT_ID

    dummy_tenant = {
        "id": test_tenant_id,
        "name": f"Role Test Tenant {generate_random_hex(6)}",
        "slug": f"role-tenant-{generate_random_hex(6)}",
        "idp_tenant_id": generate_id("idp"),
        "status": "active",
        "created_at": datetime.datetime.now().replace(tzinfo=None),
        "updated_at": datetime.datetime.now().replace(tzinfo=None),
    }
    platform_tenant = {
        "id": platform_tenant_id,
        "name": "Platform Tenant",
        "slug": "platform",
        "idp_tenant_id": "platform",
        "status": "active",
        "created_at": datetime.datetime.now().replace(tzinfo=None),
        "updated_at": datetime.datetime.now().replace(tzinfo=None),
    }
    dummy_user = {
        "id": test_user_id,
        "email": f"test_{generate_random_hex(6)}@example.com",
        "idp_user_id": generate_id("idp"),
        "name": "Test User",
        "status": "active",
        "created_at": datetime.datetime.now().replace(tzinfo=None),
        "updated_at": datetime.datetime.now().replace(tzinfo=None),
    }
    await db_session.execute(
        pg_insert(OrmTenant).values([dummy_tenant]).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(OrmTenant).values([platform_tenant]).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(OrmUser).values([dummy_user]).on_conflict_do_nothing(index_elements=["id"])
    )
    return test_tenant_id, test_user_id, platform_tenant_id


@pytest.mark.asyncio
async def test_postgres_role_repository_crud_operations(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, test_user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        # test save (new role)
        role_id = generate_id("role")
        role = DomainRole(
            id=role_id,
            tenant_id=platform_tenant_id,
            name="Test Global Role",
            description="desc",
            capabilities=["cap1", "cap2"],
        )
        await repo.save(role)

        # test get_by_id
        fetched = await repo.get_by_id(role_id)
        assert fetched is not None
        assert fetched.name == "Test Global Role"
        assert set(fetched.capabilities) == {"cap1", "cap2"}

        # test get_by_id missing
        assert await repo.get_by_id("missing") is None

        # test save (update role)
        role.name = "Updated Name"
        role.capabilities = ["cap3"]
        await repo.save(role)

        fetched_updated = await repo.get_by_id(role_id)
        assert fetched_updated is not None
        assert fetched_updated.name == "Updated Name"
        assert set(fetched_updated.capabilities) == {"cap3"}

        # test get_global_role_by_name
        fetched_global = await repo.get_global_role_by_name("Updated Name")
        assert fetched_global is not None
        assert fetched_global.id == role_id

        # test get_global_role_by_name missing
        assert await repo.get_global_role_by_name("Nonexistent") is None

        # test get_global_roles
        roles = await repo.get_global_roles()
        assert role_id in {r.id for r in roles}


@pytest.mark.asyncio
async def test_postgres_role_repository_assignments(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        role_id = generate_id("role")
        role = DomainRole(
            id=role_id,
            tenant_id=test_tenant_id,
            name="Tenant Role",
            description="desc",
            capabilities=["tenant:read"],
        )
        await repo.save(role)

        await repo.assign_user_role(test_tenant_id, user_id, role_id)

        caps = await repo.get_user_capabilities(test_tenant_id, user_id)
        assert "tenant:read" in caps

        assert await repo.has_any_tenant_memberships(user_id) is True

        await repo.remove_user_roles(test_tenant_id, user_id)

        caps_after = await repo.get_user_capabilities(test_tenant_id, user_id)
        assert len(caps_after) == 0

        assert await repo.has_any_tenant_memberships(user_id) is False


@pytest.mark.asyncio
async def test_duplicate_assignment_raises_idempotency_error(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        role_id = generate_id("role")
        role = DomainRole(
            id=role_id,
            tenant_id=test_tenant_id,
            name="Tenant Role",
            description="desc",
            capabilities=["tenant:read"],
        )
        await repo.save(role)

        await repo.assign_user_role(test_tenant_id, user_id, role_id)

        # Sub-transaction to test error safely
        async with db_session.begin_nested():
            with pytest.raises(IdempotencyConflictError):
                await repo.assign_user_role(test_tenant_id, user_id, role_id)


@pytest.mark.asyncio
async def test_assign_user_role_missing_role_error(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        with pytest.raises(ResourceNotFoundError, match="not found or is inactive"):
            await repo.assign_user_role(test_tenant_id, user_id, "role_missing")


@pytest.mark.asyncio
async def test_assign_user_role_cross_tenant_error(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        other_tenant_id = generate_id("ten")
        await db_session.execute(
            pg_insert(OrmTenant).values(
                [
                    {
                        "id": other_tenant_id,
                        "name": "Other",
                        "slug": f"other-{generate_random_hex(6)}",
                        "idp_tenant_id": f"oth-{generate_random_hex(6)}",
                        "status": "active",
                        "created_at": datetime.datetime.now().replace(tzinfo=None),
                        "updated_at": datetime.datetime.now().replace(tzinfo=None),
                    }
                ]
            )
        )
        role_other = DomainRole(
            id=generate_id("role"),
            tenant_id=other_tenant_id,
            name="x",
            description="x",
            capabilities=[],
        )
        await repo.save(role_other)

        with pytest.raises(ResourceNotFoundError):
            await repo.assign_user_role(test_tenant_id, user_id, role_other.id)


@pytest.mark.asyncio
async def test_assign_user_role_global_role_as_platform(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        role_global = DomainRole(
            id=generate_id("role"),
            tenant_id=platform_tenant_id,
            name="Global",
            description="G",
            capabilities=["g"],
        )
        await repo.save(role_global)

        await repo.assign_user_role(None, user_id, role_global.id)
        caps = await repo.get_user_capabilities(None, user_id)
        assert "g" in caps


@pytest.mark.asyncio
async def test_value_errors(db_session_factory):
    async with db_session_factory() as db_session, db_session.begin_nested():
        test_tenant_id, user_id, platform_tenant_id = await _setup_data(db_session)
        repo = PostgresRoleRepository(db_session)

        with pytest.raises(ValueError):
            await repo.assign_user_role("", user_id, "role_id")

        with pytest.raises(ValueError):
            await repo.get_user_capabilities("", user_id)

        with pytest.raises(ValueError):
            await repo.remove_user_roles("", user_id)
