"""Unit tests for the provider-agnostic `IdentitySyncService` using `IdentityProviderAdminPort`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType

import pytest
from identity.domain.constants import TenantIsolationMode
from identity.domain.dtos import EnterpriseSsoConfigDTO, ExternalIdentityRef, RealmRef
from identity.domain.exceptions import IdentityError, IdentityErrorCode
from identity.ports.outbound.identity_provider_admin_port import IdentityProviderAdminPort
from identity_worker.application.use_cases.identity_sync_service import (
    IdentityProvisioningError,
    IdentitySyncService,
    StateConflictError,
)
from identity_worker.ports.outbound.identity_sync_repository_port import (
    IdentitySyncRepositoryPort,
    IdentitySyncUnitOfWorkPort,
    SyncTenant,
    SyncUser,
)
from seedwork import generate_id
from seedwork.domain.exceptions import Result

pytestmark = [pytest.mark.asyncio]


class FakeIdentitySyncRepository(IdentitySyncRepositoryPort):
    def __init__(self, tenants: dict[str, SyncTenant], users: dict[str, SyncUser]) -> None:
        self.tenants = tenants
        self.users = users
        self.external_identities: list[tuple[str, str, str, str | None]] = []
        self.fail_on_upsert_external_identity = False

    async def get_tenant(self, tenant_id: str) -> SyncTenant | None:
        return self.tenants.get(tenant_id)

    async def update_tenant_idp_realm(self, tenant_id: str, idp_realm_name: str) -> None:
        existing = self.tenants.get(tenant_id)
        if existing is not None:
            if existing.isolation_mode == TenantIsolationMode.DEDICATED_IDP_ORG.value:
                for other_id, other in self.tenants.items():
                    if (
                        other_id != tenant_id
                        and other.isolation_mode == TenantIsolationMode.DEDICATED_IDP_ORG.value
                        and other.idp_realm_name == idp_realm_name
                    ):
                        raise RuntimeError(f"Duplicate dedicated idp_realm_name '{idp_realm_name}'")
            self.tenants[tenant_id] = SyncTenant(
                id=existing.id,
                name=existing.name,
                idp_realm_name=idp_realm_name,
                slug=existing.slug,
                isolation_mode=existing.isolation_mode,
            )

    async def get_user(self, user_id: str) -> SyncUser | None:
        return self.users.get(user_id)

    async def get_user_for_update(self, user_id: str) -> SyncUser | None:
        return self.users.get(user_id)

    async def update_user_idp_mapping(self, user_id: str, idp_user_id: str) -> None:
        if user_id in self.users:
            self.users[user_id] = SyncUser(id=user_id, idp_user_id=idp_user_id)

    async def upsert_external_identity(
        self,
        *,
        user_id: str,
        idp_issuer: str,
        idp_subject: str,
        idp_realm_name: str | None = None,
    ) -> None:
        if self.fail_on_upsert_external_identity:
            raise RuntimeError("Simulated DB failure while persisting external identity link")
        self.external_identities.append((user_id, idp_issuer, idp_subject, idp_realm_name))

    async def find_external_identity_realm(self, idp_subject: str) -> str | None:
        for _, _, subj, realm in self.external_identities:
            if subj == idp_subject:
                return realm
        return None


class FakeIdentitySyncUnitOfWork(IdentitySyncUnitOfWorkPort):
    def __init__(self, repo: FakeIdentitySyncRepository) -> None:
        self._repo = repo
        self.committed = False
        self.rolled_back = False

    @property
    def repo(self) -> FakeIdentitySyncRepository:
        return self._repo

    async def __aenter__(self) -> FakeIdentitySyncUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeIdentityProviderAdmin(IdentityProviderAdminPort):
    def __init__(self) -> None:
        self.created_realms: dict[str, str] = {}
        self.users: dict[str, dict[str, object]] = {}
        self.deleted_subjects: list[tuple[str, str]] = []
        self.fail_realm_provisioning = False
        self.fail_create_user = False

    async def create_user(
        self,
        *,
        realm: str,
        email: str,
        display_name: str,
        initial_password: str | None = None,
    ) -> Result[ExternalIdentityRef, IdentityError]:
        if self.fail_create_user:
            return Result.fail(
                IdentityError(code=IdentityErrorCode.IDP_ADMIN_ERROR, message="IdP create failed")
            )
        subject = generate_id("idp_sub")
        self.users[subject] = {
            "realm": realm,
            "email": email,
            "display_name": display_name,
            "active": True,
        }
        return Result.ok(
            ExternalIdentityRef(
                idp_issuer="http://localhost:8080",
                idp_subject=subject,
                idp_realm_name=realm,
                created=True,
            )
        )

    async def update_user(
        self,
        *,
        realm: str,
        external_subject: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> Result[None, IdentityError]:
        if external_subject in self.users:
            if display_name is not None:
                self.users[external_subject]["display_name"] = display_name
            if email is not None:
                self.users[external_subject]["email"] = email
        return Result.ok(None)

    async def set_user_active(
        self,
        *,
        realm: str,
        external_subject: str,
        active: bool,
    ) -> Result[None, IdentityError]:
        if external_subject in self.users:
            self.users[external_subject]["active"] = active
        return Result.ok(None)

    async def delete_user(
        self,
        *,
        realm: str,
        external_subject: str,
    ) -> Result[None, IdentityError]:
        self.users.pop(external_subject, None)
        self.deleted_subjects.append((realm, external_subject))
        return Result.ok(None)

    async def provision_dedicated_enterprise_realm(
        self,
        *,
        slug: str,
        display_name: str,
        sso_config: EnterpriseSsoConfigDTO | None = None,
    ) -> Result[RealmRef, IdentityError]:
        if self.fail_realm_provisioning:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_ADMIN_ERROR,
                    message="Dedicated enterprise realm creation failed",
                )
            )
        realm_name = f"org_{slug}"
        self.created_realms[slug] = realm_name
        return Result.ok(
            RealmRef(
                idp_issuer="http://localhost:8080",
                realm_name=realm_name,
                display_name=display_name,
            )
        )


def _make_uow_factory(
    tenants: dict[str, SyncTenant] | None = None,
    users: dict[str, SyncUser] | None = None,
) -> tuple[
    FakeIdentitySyncRepository,
    FakeIdentitySyncUnitOfWork,
    Callable[[], AbstractAsyncContextManager[IdentitySyncUnitOfWorkPort]],
]:
    repo = FakeIdentitySyncRepository(tenants=tenants or {}, users=users or {})
    uow = FakeIdentitySyncUnitOfWork(repo)
    return repo, uow, (lambda: uow)


async def test_handle_tenant_provisioned_pooled_uses_global_realm() -> None:
    tenant_1 = generate_id("ten")
    tenant_2 = generate_id("ten")
    repo, uow, uow_factory = _make_uow_factory(
        tenants={
            tenant_1: SyncTenant(
                id=tenant_1,
                name="Acme SMB",
                idp_realm_name=None,
                slug="acme-smb",
                isolation_mode=TenantIsolationMode.POOLED_REALM.value,
            ),
            tenant_2: SyncTenant(
                id=tenant_2,
                name="Beta SMB",
                idp_realm_name=None,
                slug="beta-smb",
                isolation_mode=TenantIsolationMode.POOLED_REALM.value,
            ),
        }
    )
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    await service.handle_tenant_provisioned(tenant_1)
    await service.handle_tenant_provisioned(tenant_2)

    assert admin.created_realms == {}
    assert repo.tenants[tenant_1].idp_realm_name == "soopa-global"
    assert repo.tenants[tenant_2].idp_realm_name == "soopa-global"
    assert uow.committed is True


async def test_handle_tenant_provisioned_dedicated_enterprise_creates_realm() -> None:
    tenant_id = generate_id("ten")
    repo, uow, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme Enterprise",
                idp_realm_name=None,
                slug="acme_ent",
                isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG.value,
            )
        }
    )
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    await service.handle_tenant_provisioned(tenant_id)

    assert admin.created_realms == {"acme_ent": "org_acme_ent"}
    assert repo.tenants[tenant_id].idp_realm_name == "org_acme_ent"
    assert uow.committed is True


async def test_handle_tenant_provisioned_idempotent_when_already_synced() -> None:
    tenant_id = generate_id("ten")
    _, uow, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme",
                idp_realm_name="org_acme",
                slug="acme",
                isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG.value,
            )
        }
    )
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    await service.handle_tenant_provisioned(tenant_id)

    assert admin.created_realms == {}
    assert uow.committed is False


async def test_handle_tenant_provisioned_raises_when_dedicated_realm_fails() -> None:
    tenant_id = generate_id("ten")
    _, _, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme Ent",
                idp_realm_name=None,
                slug="acme_ent",
                isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG.value,
            )
        }
    )
    admin = FakeIdentityProviderAdmin()
    admin.fail_realm_provisioning = True
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    with pytest.raises(IdentityProvisioningError):
        await service.handle_tenant_provisioned(tenant_id)


async def test_handle_user_created_creates_in_idp_and_links_external_identity() -> None:
    tenant_id = generate_id("ten")
    user_id = generate_id("iam_usr")
    repo, uow, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme",
                idp_realm_name="soopa-global",
                slug="acme",
                isolation_mode=TenantIsolationMode.POOLED_REALM.value,
            )
        },
        users={user_id: SyncUser(id=user_id, idp_user_id=None)},
    )
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    await service.handle_user_created(
        user_id=user_id,
        tenant_id=tenant_id,
        email="alice@acme.com",
        first_name="Alice",
        last_name="Smith",
        role="TenantAdmin",
    )

    assert uow.committed is True
    assert repo.users[user_id].idp_user_id is not None
    assert len(repo.external_identities) == 1
    linked_user, issuer, subject, realm = repo.external_identities[0]
    assert linked_user == user_id
    assert issuer == "http://localhost:8080"
    assert subject == repo.users[user_id].idp_user_id
    assert realm == "soopa-global"


async def test_handle_user_created_raises_conflict_for_unprovisioned_enterprise_tenant() -> None:
    tenant_id = generate_id("ten")
    user_id = generate_id("iam_usr")
    _, _, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme Ent",
                idp_realm_name=None,
                slug="acme_ent",
                isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG.value,
            )
        },
        users={user_id: SyncUser(id=user_id, idp_user_id=None)},
    )
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    with pytest.raises(StateConflictError):
        await service.handle_user_created(
            user_id=user_id,
            tenant_id=tenant_id,
            email="alice@acme.com",
            first_name="Alice",
            last_name="Smith",
            role="TenantAdmin",
        )


async def test_handle_user_created_compensates_by_deleting_idp_user_on_db_failure() -> None:
    tenant_id = generate_id("ten")
    user_id = generate_id("iam_usr")
    repo, uow, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme",
                idp_realm_name="soopa-global",
                slug="acme",
            )
        },
        users={user_id: SyncUser(id=user_id, idp_user_id=None)},
    )
    repo.fail_on_upsert_external_identity = True
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    with pytest.raises(RuntimeError, match="Simulated DB failure"):
        await service.handle_user_created(
            user_id=user_id,
            tenant_id=tenant_id,
            email="alice@acme.com",
            first_name="Alice",
            last_name="Smith",
            role="TenantAdmin",
        )

    assert uow.rolled_back is True
    assert len(admin.deleted_subjects) == 1
    assert admin.users == {}


async def test_handle_user_update_toggle_and_delete() -> None:
    tenant_id = generate_id("ten")
    _, _, uow_factory = _make_uow_factory(
        tenants={
            tenant_id: SyncTenant(
                id=tenant_id,
                name="Acme",
                idp_realm_name="soopa-global",
                slug="acme",
            )
        }
    )
    admin = FakeIdentityProviderAdmin()
    admin.users["idp_sub_1"] = {
        "realm": "soopa-global",
        "email": "bob@acme.com",
        "display_name": "Bob Old",
        "active": True,
    }
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    await service.handle_user_updated("idp_sub_1", tenant_id, "Bob", "New", "TenantUser")
    assert admin.users["idp_sub_1"]["display_name"] == "Bob New"

    await service.handle_user_status_toggled("idp_sub_1", tenant_id, "deactivate")
    assert admin.users["idp_sub_1"]["active"] is False

    await service.handle_user_deleted("idp_sub_1")
    assert ("soopa-global", "idp_sub_1") in admin.deleted_subjects


async def test_handle_user_deleted_resolves_dedicated_enterprise_realm() -> None:
    repo, _, uow_factory = _make_uow_factory()
    repo.external_identities.append(
        ("iam_usr_ent1", "http://localhost:8080", "idp_sub_ent1", "org_acme_enterprise")
    )
    admin = FakeIdentityProviderAdmin()
    service = IdentitySyncService(idp_admin=admin, uow_factory=uow_factory)

    await service.handle_user_deleted("idp_sub_ent1")
    assert admin.deleted_subjects == [("org_acme_enterprise", "idp_sub_ent1")]
