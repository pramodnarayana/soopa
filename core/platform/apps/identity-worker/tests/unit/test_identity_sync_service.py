import uuid
from typing import Literal

import pytest
from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from identity_worker.application.use_cases.identity_sync_service import (
    IdentitySyncService,
    StateConflictError,
)
from identity_worker.ports.outbound.identity_provider_port import IdentityProviderPort
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

pytestmark = pytest.mark.asyncio


class FakeIdentityProvider(IdentityProviderPort):
    def __init__(self):
        self.synced_tenants = set()

    async def sync_tenant(self, tenant_id: str) -> None:
        self.synced_tenants.add(tenant_id)


class FakeUserIdentityProvider(UserIdentityProviderPort):
    def __init__(self):
        self.users = {}
        self.user_roles = {}
        self.user_status = {}
        self.fail_role_assignment = False

    async def create_user(
        self,
        org_id: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> str:
        user_id = f"idp_{uuid.uuid4()}"
        self.users[user_id] = {
            "org_id": org_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
        }
        self.user_status[user_id] = "active"
        return user_id

    async def assign_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        if self.fail_role_assignment:
            raise RuntimeError("role assignment failed")
        self.user_roles[user_id] = role

    async def update_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        self.user_roles[user_id] = role

    async def update_user_profile(
        self,
        user_id: str,
        org_id: str,
        first_name: str,
        last_name: str,
    ) -> None:
        if user_id in self.users:
            self.users[user_id]["first_name"] = first_name
            self.users[user_id]["last_name"] = last_name

    async def delete_user(self, user_id: str) -> None:
        if user_id in self.users:
            del self.users[user_id]

    async def toggle_user_status(
        self,
        user_id: str,
        org_id: str,
        action: Literal["activate", "deactivate"],
    ) -> None:
        self.user_status[user_id] = action


@pytest.fixture
async def fakes():
    return FakeIdentityProvider(), FakeUserIdentityProvider()


@pytest.fixture
async def setup_db(db_session_factory):
    async with db_session_factory() as session:
        # Create a fully provisioned tenant
        tenant_id = str(uuid.uuid4())
        idp_tenant_id = f"idp_org_{uuid.uuid4()}"
        tenant = DbTenant(
            id=tenant_id, name="Test Corp", slug="test-corp", idp_tenant_id=idp_tenant_id
        )
        session.add(tenant)

        # Create an unprovisioned tenant
        unprovisioned_tenant_id = str(uuid.uuid4())
        unprovisioned_tenant = DbTenant(
            id=unprovisioned_tenant_id, name="New Corp", slug="new-corp", idp_tenant_id=None
        )
        session.add(unprovisioned_tenant)

        # Create a user
        user_id = str(uuid.uuid4())
        user = DbUser(id=user_id, email="john@test.com", name="John Doe", status="active")
        session.add(user)

        await session.commit()

    return {
        "tenant_id": tenant_id,
        "idp_tenant_id": idp_tenant_id,
        "unprovisioned_tenant_id": unprovisioned_tenant_id,
        "user_id": user_id,
    }


async def test_handle_tenant_provisioned(fakes, db_session_factory, setup_db):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    tenant_id = setup_db["tenant_id"]
    await service.handle_tenant_provisioned(tenant_id)

    assert tenant_id in idp.synced_tenants


async def test_handle_user_created(fakes, db_session_factory, setup_db):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    user_id = setup_db["user_id"]
    tenant_id = setup_db["tenant_id"]

    await service.handle_user_created(
        user_id=user_id,
        tenant_id=tenant_id,
        email="john@test.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    assert len(user_idp.users) == 1
    created_idp_user_id = next(iter(user_idp.users.keys()))

    # Assert fakes state
    assert user_idp.users[created_idp_user_id]["email"] == "john@test.com"
    assert user_idp.user_roles[created_idp_user_id] == "admin"

    # Assert database updated with idp_user_id
    async with db_session_factory() as session:
        result = await session.execute(DbUser.__table__.select().where(DbUser.id == user_id))
        db_user = result.fetchone()
        assert db_user.idp_user_id == created_idp_user_id


async def test_handle_user_created_unprovisioned_tenant(fakes, db_session_factory, setup_db):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    user_id = setup_db["user_id"]
    unprovisioned_tenant_id = setup_db["unprovisioned_tenant_id"]

    with pytest.raises(StateConflictError):
        await service.handle_user_created(
            user_id=user_id,
            tenant_id=unprovisioned_tenant_id,
            email="john@test.com",
            first_name="John",
            last_name="Doe",
            role="admin",
        )


async def test_handle_user_created_missing_local_user_has_no_external_side_effects(
    fakes, db_session_factory, setup_db
):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    await service.handle_user_created(
        user_id=str(uuid.uuid4()),
        tenant_id=setup_db["tenant_id"],
        email="missing@test.com",
        first_name="Missing",
        last_name="User",
        role="admin",
    )

    assert user_idp.users == {}
    assert user_idp.user_roles == {}


async def test_handle_user_created_reconciles_existing_idp_user(
    fakes, db_session_factory, setup_db
):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)
    existing_idp_user_id = "idp_existing"

    async with db_session_factory() as session:
        user = await session.get(DbUser, setup_db["user_id"])
        user.idp_user_id = existing_idp_user_id
        await session.commit()

    await service.handle_user_created(
        user_id=setup_db["user_id"],
        tenant_id=setup_db["tenant_id"],
        email="john@test.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    assert user_idp.users == {}
    assert user_idp.user_roles[existing_idp_user_id] == "admin"


async def test_handle_user_created_compensates_failed_role_assignment(
    fakes, db_session_factory, setup_db
):
    idp, user_idp = fakes
    user_idp.fail_role_assignment = True
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    with pytest.raises(RuntimeError, match="role assignment failed"):
        await service.handle_user_created(
            user_id=setup_db["user_id"],
            tenant_id=setup_db["tenant_id"],
            email="john@test.com",
            first_name="John",
            last_name="Doe",
            role="admin",
        )

    assert user_idp.users == {}
    async with db_session_factory() as session:
        user = await session.get(DbUser, setup_db["user_id"])
        assert user.idp_user_id is None


async def test_handle_user_updated(fakes, db_session_factory, setup_db):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    # Pre-populate fake user
    idp_user_id = await user_idp.create_user(
        setup_db["idp_tenant_id"], "old@test.com", "Old", "Name"
    )

    await service.handle_user_updated(
        idp_user_id=idp_user_id,
        tenant_id=setup_db["tenant_id"],
        first_name="New",
        last_name="Name",
        role="member",
    )

    assert user_idp.users[idp_user_id]["first_name"] == "New"
    assert user_idp.user_roles[idp_user_id] == "member"


async def test_handle_user_status_toggled(fakes, db_session_factory, setup_db):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    idp_user_id = await user_idp.create_user(setup_db["idp_tenant_id"], "test@test.com", "F", "L")
    assert user_idp.user_status[idp_user_id] == "active"

    await service.handle_user_status_toggled(
        idp_user_id=idp_user_id, tenant_id=setup_db["tenant_id"], action="deactivate"
    )

    assert user_idp.user_status[idp_user_id] == "deactivate"


async def test_handle_user_deleted(fakes, db_session_factory, setup_db):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, db_session_factory)

    idp_user_id = await user_idp.create_user(setup_db["idp_tenant_id"], "test@test.com", "F", "L")
    assert idp_user_id in user_idp.users

    await service.handle_user_deleted(idp_user_id=idp_user_id)

    assert idp_user_id not in user_idp.users
