import os
import uuid
from unittest.mock import AsyncMock

import pytest
from database.models.identity import Tenant as DbTenant
from identity_worker.adapters.outbound.identity_provider.zitadel_identity_provider import (
    ZitadelIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_projects_adapter import (
    ZitadelProjectsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_users_adapter import (
    ZitadelUsersAdapter,
)
from identity_worker.domain.exceptions import IdentityProviderPortError
from seedwork import generate_id

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("ZITADEL_MACHINE_KEY"),
        reason="ZITADEL_MACHINE_KEY is not set",
    ),
]


@pytest.fixture
def zitadel_projects_adapter():
    # Will automatically pick up env vars via config.py
    return ZitadelProjectsAdapter()


@pytest.fixture
def zitadel_orgs_adapter(zitadel_projects_adapter):
    return ZitadelOrganizationsAdapter(project_provider=zitadel_projects_adapter)


@pytest.fixture
def zitadel_users_adapter():
    adapter = ZitadelUsersAdapter()
    adapter.default_user_password = "ComplexPassword123!"  # noqa: S105
    return adapter


@pytest.fixture
async def setup_tenant_db(db_session_factory):
    async with db_session_factory() as session:
        tenant_id = generate_id("id")
        tenant = DbTenant(
            id=tenant_id,
            name="Test Corp Identity Sync",
            slug=f"test-corp-{tenant_id[:8]}",
            idp_tenant_id=None,
        )
        session.add(tenant)
        await session.commit()
    return tenant_id


async def test_full_zitadel_lifecycle(
    zitadel_orgs_adapter: ZitadelOrganizationsAdapter,
    zitadel_projects_adapter: ZitadelProjectsAdapter,
    zitadel_users_adapter: ZitadelUsersAdapter,
):
    """
    A full narrow integration test testing the actual local Zitadel container.
    This creates an organization, provisions users, assigns roles, updates them, and then deletes the organization.
    """
    # 1. Test Organization Creation
    test_org_name = f"Test Integration Org {uuid.uuid4()}"
    org_id, grant_succeeded = await zitadel_orgs_adapter.create_organization(test_org_name)
    assert org_id is not None
    assert grant_succeeded is True, "Project grant should be successful"

    try:
        # 2. Test Get Roles
        roles = await zitadel_projects_adapter.get_roles()
        assert len(roles) > 0
        role_keys = [r.key for r in roles]
        assert "PlatformAdmin" in role_keys or "TenantAdmin" in role_keys

        # 3. Test Create User
        test_email = f"testuser_{uuid.uuid4()}@example.com"
        user_id = await zitadel_users_adapter.create_user(
            org_id=org_id,
            email=test_email,
            first_name="Integration",
            last_name="TestUser",
        )
        assert user_id is not None

        # 4. Test Update User Profile
        await zitadel_users_adapter.update_user_profile(
            user_id=user_id,
            org_id=org_id,
            first_name="UpdatedIntegration",
            last_name="UpdatedTestUser",
        )

        # 5. Test Assign Role
        await zitadel_users_adapter.assign_tenant_role(
            user_id=user_id,
            org_id=org_id,
            role="TenantAdmin" if "TenantAdmin" in role_keys else role_keys[0],
        )

        # 6. Test Update Role
        await zitadel_users_adapter.update_tenant_role(
            user_id=user_id,
            org_id=org_id,
            role="TenantUser" if "TenantUser" in role_keys else role_keys[0],
        )

        # 7. Test Get Users
        users = await zitadel_projects_adapter.get_users(org_id=org_id)
        assert len(users) >= 1
        found = next((u for u in users if u.id == user_id), None)
        assert found is not None
        assert found.email == test_email
        assert found.first_name == "UpdatedIntegration"
        assert found.last_name == "UpdatedTestUser"

        # 8. Test Toggle User Status
        await zitadel_users_adapter.toggle_user_status(
            user_id=user_id, org_id=org_id, action="deactivate"
        )

        # Idempotent toggle
        await zitadel_users_adapter.toggle_user_status(
            user_id=user_id, org_id=org_id, action="deactivate"
        )

        await zitadel_users_adapter.toggle_user_status(
            user_id=user_id, org_id=org_id, action="activate"
        )

        # 9. Test Remove Role
        await zitadel_users_adapter.remove_tenant_role(user_id=user_id, org_id=org_id)

        # 10. Test Delete User
        await zitadel_users_adapter.delete_user(user_id=user_id)

        # Idempotent delete user
        await zitadel_users_adapter.delete_user(user_id=user_id)

    finally:
        # 11. Test Delete Organization (Cleanup)
        await zitadel_orgs_adapter.delete_organization(org_id)


async def test_update_organization_name(zitadel_orgs_adapter: ZitadelOrganizationsAdapter):
    test_org_name = f"Test Update Org {uuid.uuid4()}"
    org_id, _ = await zitadel_orgs_adapter.create_organization(test_org_name)
    try:
        await zitadel_orgs_adapter.update_organization_name(org_id, test_org_name + " Updated")
    finally:
        await zitadel_orgs_adapter.delete_organization(org_id)


async def test_toggle_organization_status(zitadel_orgs_adapter: ZitadelOrganizationsAdapter):
    test_org_name = f"Test Toggle Org {uuid.uuid4()}"
    org_id, _ = await zitadel_orgs_adapter.create_organization(test_org_name)
    try:
        await zitadel_orgs_adapter.toggle_organization_status(org_id, active=False)
        await zitadel_orgs_adapter.toggle_organization_status(org_id, active=True)
    finally:
        await zitadel_orgs_adapter.delete_organization(org_id)


async def test_sync_tenant_success(
    db_session_factory, setup_tenant_db, zitadel_orgs_adapter: ZitadelOrganizationsAdapter
):
    provider = ZitadelIdentityProviderPort(zitadel_orgs_adapter, db_session_factory)
    await provider.sync_tenant(setup_tenant_db)

    async with db_session_factory() as session:
        tenant = await session.get(DbTenant, setup_tenant_db)
        assert tenant.idp_tenant_id is not None

        # Cleanup from Zitadel
        await zitadel_orgs_adapter.delete_organization(tenant.idp_tenant_id)


async def test_sync_tenant_not_found(
    db_session_factory, zitadel_orgs_adapter: ZitadelOrganizationsAdapter
):
    provider = ZitadelIdentityProviderPort(zitadel_orgs_adapter, db_session_factory)
    await provider.sync_tenant("missing-id")


async def test_sync_tenant_already_synced(
    db_session_factory, zitadel_orgs_adapter: ZitadelOrganizationsAdapter
):
    async with db_session_factory() as session:
        tenant_id = generate_id("id")
        tenant = DbTenant(
            id=tenant_id,
            name="Test Corp Already Synced",
            slug=f"synced-{tenant_id[:8]}",
            idp_tenant_id="existing-id",
        )
        session.add(tenant)
        await session.commit()

    provider = ZitadelIdentityProviderPort(zitadel_orgs_adapter, db_session_factory)
    await provider.sync_tenant(tenant_id)


async def test_sync_tenant_grant_failed(db_session_factory, setup_tenant_db):
    org_provider = AsyncMock()
    org_provider.create_organization.return_value = ("org-id-123", False)

    provider = ZitadelIdentityProviderPort(org_provider, db_session_factory)
    with pytest.raises(IdentityProviderPortError, match="project grant could not be assigned"):
        await provider.sync_tenant(setup_tenant_db)
