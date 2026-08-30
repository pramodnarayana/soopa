import datetime

import pytest
from database.models.identity import IdentityOutbox as OrmIdentityOutbox
from database.models.identity import Role as OrmRole
from database.models.identity import Tenant as OrmTenant
from database.models.identity import UserRole as OrmUserRole
from seedwork import generate_id, generate_random_hex
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from identity.domain.constants import DomainIdPrefix as IamPrefix
from identity.domain.events import UserCreatedEvent
from identity.domain.models.user import User

pytestmark = pytest.mark.integration


@pytest.fixture
def dummy_tenant_data() -> dict:
    tenant_id = generate_id(IamPrefix.TENANT)
    return {
        "id": tenant_id,
        "name": f"User Repo Tenant {generate_random_hex(6)}",
        "slug": f"user-tenant-{generate_random_hex(6)}",
        "idp_tenant_id": "idp_ten_123",
        "status": "active",
        "created_at": datetime.datetime.now().replace(tzinfo=None),
        "updated_at": datetime.datetime.now().replace(tzinfo=None),
    }


@pytest.fixture
def dummy_role_data(dummy_tenant_data: dict) -> dict:
    return {
        "id": generate_id(IamPrefix.ROLE),
        "name": f"User Repo Role {generate_random_hex(6)}",
        "description": "Role for user repo tests",
        "tenant_id": dummy_tenant_data["id"],
        "capabilities": ["test:read"],
    }


@pytest.mark.asyncio
async def test_user_repository_lifecycle(
    db_session_factory, dummy_tenant_data, dummy_role_data
) -> None:
    async with db_session_factory() as db_session, db_session.begin_nested():
        repo = PostgresUserRepository(db_session)

        # Pre-requisites: Insert tenant and role
        await db_session.execute(
            pg_insert(OrmTenant)
            .values([dummy_tenant_data])
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db_session.execute(
            pg_insert(OrmRole)
            .values([dummy_role_data])
            .on_conflict_do_nothing(index_elements=["id"])
        )

        # 1. Save User (Create)
        user_id = generate_id(IamPrefix.USER)
        idp_user_id = "idp_usr_123"
        email = "test.user@example.com"
        now = datetime.datetime.now(datetime.UTC)
        user = User(
            id=user_id,
            idp_user_id=idp_user_id,
            email=email,
            name="Test User",
            status="active",
            created_at=now,
            updated_at=now,
        )

        # Add a domain event to test outbox flushing
        user.domain_events.append(
            UserCreatedEvent(
                user_id=user.id,
                tenant_id=dummy_tenant_data["id"],
                email=user.email,
                first_name="Test",
                last_name="User",
                role=dummy_role_data["name"],
            )
        )

        await repo.save(user)

        # Verify Outbox flushed
        outbox_stmt = select(OrmIdentityOutbox).where(
            OrmIdentityOutbox.payload["user_id"].astext == user.id
        )
        outbox_events = (await db_session.execute(outbox_stmt)).scalars().all()
        assert len(outbox_events) == 1
        assert outbox_events[0].event_type == "UserInvited"
        assert len(user.domain_events) == 0

        # 2. Find by ID
        fetched_by_id = await repo.find_by_id(user.id)
        assert fetched_by_id is not None
        assert fetched_by_id.email == email

        # 3. Find by IDP User ID
        fetched_by_idp = await repo.find_by_idp_user_id(idp_user_id)
        assert fetched_by_idp is not None
        assert fetched_by_idp.id == user.id

        # 4. Find by Email
        fetched_by_email = await repo.find_by_email(email)
        assert fetched_by_email is not None
        assert fetched_by_email.id == user.id

        # 4a. Find by Email - Missing
        assert await repo.find_by_email("missing@example.com") is None

        # 4b. Find by IDP User ID - Missing
        assert await repo.find_by_idp_user_id("idp_missing") is None

        # 5. Link to Tenant and Role (UserRole) manually to test find_users_by_tenant
        await db_session.execute(
            pg_insert(OrmUserRole).values(
                id=generate_id(IamPrefix.USER_ROLE),
                user_id=user.id,
                role_id=dummy_role_data["id"],
                tenant_id=dummy_tenant_data["id"],
            )
        )

        # 6. Find Users By Tenant
        users_in_tenant = await repo.find_users_by_tenant(dummy_tenant_data["id"])
        assert len(users_in_tenant) >= 1
        assert any(u.id == user.id for u in users_in_tenant)

        # 7. Find By ID and Tenant
        user_in_tenant = await repo.find_by_id_and_tenant(user.id, dummy_tenant_data["id"])
        assert user_in_tenant is not None
        assert user_in_tenant.role == dummy_role_data["name"]

        # 7a. Find By ID and Tenant - Missing
        assert await repo.find_by_id_and_tenant(user.id, "iam_ten_missing") is None

        # 8. Check Tenant Memberships
        has_memberships = await repo.has_any_tenant_memberships(user.id)
        assert has_memberships is True

        # 9. Update User
        user.name = "Updated User"
        await repo.save(user)
        fetched_updated = await repo.find_by_id(user.id)
        assert fetched_updated.name == "Updated User"

        # 10. Delete User
        await repo.delete(user)
        fetched_deleted = await repo.find_by_id(user.id)
        assert fetched_deleted is None
