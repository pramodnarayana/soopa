import uuid
from typing import Literal

import pytest
from identity_worker.application.use_cases.identity_sync_service import (
    IdentitySyncService,
    StateConflictError,
)
from identity_worker.ports.outbound.identity_provider_port import IdentityProviderPort
from identity_worker.ports.outbound.identity_sync_repository_port import (
    IdentitySyncRepositoryPort,
    IdentitySyncUnitOfWorkPort,
    SyncTenant,
    SyncUser,
)
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort
from seedwork import generate_id

pytestmark = [pytest.mark.asyncio]


class FakeIdentitySyncRepository(IdentitySyncRepositoryPort):
    def __init__(self, tenants: dict[str, SyncTenant], users: dict[str, SyncUser]):
        self.tenants = tenants
        self.users = users

    async def get_tenant(self, tenant_id: str) -> SyncTenant | None:
        return self.tenants.get(tenant_id)

    async def get_user(self, user_id: str) -> SyncUser | None:
        return self.users.get(user_id)

    async def get_user_for_update(self, user_id: str) -> SyncUser | None:
        return self.users.get(user_id)

    async def update_user_idp_mapping(self, user_id: str, idp_user_id: str) -> None:
        if user_id in self.users:
            self.users[user_id] = SyncUser(id=user_id, idp_user_id=idp_user_id)


class FakeIdentitySyncUnitOfWork(IdentitySyncUnitOfWorkPort):
    def __init__(self, repo: FakeIdentitySyncRepository):
        self.repo = repo
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeIdentitySyncUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeIdentityProvider(IdentityProviderPort):
    def __init__(self):
        self.synced_tenants = set()

    async def sync_tenant(self, tenant_id: str) -> None:
        self.synced_tenants.add(tenant_id)

    async def update_organization_name(self, org_id: str, name: str) -> None:
        pass

    async def toggle_organization_status(self, org_id: str, active: bool) -> None:
        pass

    async def delete_organization(self, org_id: str) -> None:
        pass

    async def grant_project_to_organization(self, org_id: str, project_id: str) -> None:
        pass

    async def revoke_project_from_organization(self, org_id: str, project_id: str) -> None:
        pass


class FakeUserIdentityProvider(UserIdentityProviderPort):
    def __init__(self):
        self.users = {}
        self.user_roles = {}
        self.user_status = {}
        self.fail_role_assignment = False

    async def create_user(
        self,
        org_id: str,
        user_id: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> tuple[str, bool]:
        self.users[user_id] = {
            "org_id": org_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
        }
        self.user_status[user_id] = "active"
        return user_id, True

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
def fakes():
    return FakeIdentityProvider(), FakeUserIdentityProvider()


@pytest.fixture
def test_data():
    tenant_id = generate_id("id")
    idp_tenant_id = f"idp_org_{uuid.uuid4()}"
    unprovisioned_tenant_id = generate_id("id")
    user_id = generate_id("id")

    tenants = {
        tenant_id: SyncTenant(id=tenant_id, idp_tenant_id=idp_tenant_id),
        unprovisioned_tenant_id: SyncTenant(id=unprovisioned_tenant_id, idp_tenant_id=None),
    }
    users = {
        user_id: SyncUser(id=user_id, idp_user_id=None),
    }
    return {
        "tenant_id": tenant_id,
        "idp_tenant_id": idp_tenant_id,
        "unprovisioned_tenant_id": unprovisioned_tenant_id,
        "user_id": user_id,
        "tenants": tenants,
        "users": users,
    }


@pytest.fixture
def uow_factory(test_data):
    repo = FakeIdentitySyncRepository(tenants=test_data["tenants"], users=test_data["users"])
    return lambda: FakeIdentitySyncUnitOfWork(repo)


async def test_handle_tenant_provisioned(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    tenant_id = test_data["tenant_id"]
    await service.handle_tenant_provisioned(tenant_id)

    assert tenant_id in idp.synced_tenants


async def test_handle_user_created(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    user_id = test_data["user_id"]
    tenant_id = test_data["tenant_id"]

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

    # Assert repository state updated with idp_user_id
    assert test_data["users"][user_id].idp_user_id == created_idp_user_id


async def test_handle_user_created_unprovisioned_tenant(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    user_id = test_data["user_id"]
    unprovisioned_tenant_id = test_data["unprovisioned_tenant_id"]

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
    fakes, uow_factory, test_data
):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    await service.handle_user_created(
        user_id=generate_id("id"),
        tenant_id=test_data["tenant_id"],
        email="missing@test.com",
        first_name="Missing",
        last_name="User",
        role="admin",
    )

    assert user_idp.users == {}
    assert user_idp.user_roles == {}


async def test_handle_user_created_reconciles_existing_idp_user(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)
    existing_idp_user_id = "idp_existing"

    test_data["users"][test_data["user_id"]] = SyncUser(
        id=test_data["user_id"], idp_user_id=existing_idp_user_id
    )

    await service.handle_user_created(
        user_id=test_data["user_id"],
        tenant_id=test_data["tenant_id"],
        email="john@test.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    assert user_idp.users == {}
    assert user_idp.user_roles[existing_idp_user_id] == "admin"


async def test_handle_user_created_compensates_failed_role_assignment(
    fakes, uow_factory, test_data
):
    idp, user_idp = fakes
    user_idp.fail_role_assignment = True
    service = IdentitySyncService(idp, user_idp, uow_factory)

    with pytest.raises(RuntimeError, match="role assignment failed"):
        await service.handle_user_created(
            user_id=test_data["user_id"],
            tenant_id=test_data["tenant_id"],
            email="john@test.com",
            first_name="John",
            last_name="Doe",
            role="admin",
        )

    assert user_idp.users == {}
    assert test_data["users"][test_data["user_id"]].idp_user_id is None


async def test_handle_user_updated(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    # Pre-populate fake user
    idp_user_id, _ = await user_idp.create_user(
        test_data["idp_tenant_id"], f"idp_{uuid.uuid4()}", "old@test.com", "Old", "Name"
    )

    await service.handle_user_updated(
        idp_user_id=idp_user_id,
        tenant_id=test_data["tenant_id"],
        first_name="New",
        last_name="Name",
        role="member",
    )

    assert user_idp.users[idp_user_id]["first_name"] == "New"
    assert user_idp.user_roles[idp_user_id] == "member"


async def test_handle_user_status_toggled(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    idp_user_id, _ = await user_idp.create_user(
        test_data["idp_tenant_id"], f"idp_{uuid.uuid4()}", "test@test.com", "F", "L"
    )
    assert user_idp.user_status[idp_user_id] == "active"

    await service.handle_user_status_toggled(
        idp_user_id=idp_user_id, tenant_id=test_data["tenant_id"], action="deactivate"
    )

    assert user_idp.user_status[idp_user_id] == "deactivate"


async def test_handle_user_deleted(fakes, uow_factory, test_data):
    idp, user_idp = fakes
    service = IdentitySyncService(idp, user_idp, uow_factory)

    idp_user_id, _ = await user_idp.create_user(
        test_data["idp_tenant_id"], f"idp_{uuid.uuid4()}", "test@test.com", "F", "L"
    )
    assert idp_user_id in user_idp.users

    await service.handle_user_deleted(idp_user_id=idp_user_id)

    assert idp_user_id not in user_idp.users
