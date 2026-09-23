import pytest

pytestmark = pytest.mark.integration

import os
import uuid

import pytest
from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from identity_worker.adapters.outbound.database.identity_sync_repository import (
    PostgresIdentitySyncUnitOfWork,
)
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
from identity_worker.application.use_cases.identity_sync_service import IdentitySyncService
from identity_worker.config.settings import get_settings
from seedwork import generate_id

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("ZITADEL_MACHINE_KEY")
        or "test-private-key" in os.environ.get("ZITADEL_MACHINE_KEY", "")
        or "fake-private-key" in os.environ.get("ZITADEL_MACHINE_KEY", ""),
        reason="ZITADEL_MACHINE_KEY is not set or is a dummy key",
    ),
]


@pytest.fixture
def zitadel_projects_adapter():
    return ZitadelProjectsAdapter(settings=get_settings())


@pytest.fixture
def zitadel_orgs_adapter(zitadel_projects_adapter):
    return ZitadelOrganizationsAdapter(
        project_provider=zitadel_projects_adapter, settings=get_settings()
    )


@pytest.fixture
def zitadel_users_adapter():
    adapter = ZitadelUsersAdapter()
    adapter.default_user_password = f"Pass_{uuid.uuid4().hex}!1A"
    return adapter


@pytest.fixture
def identity_sync_service(
    zitadel_orgs_adapter, zitadel_users_adapter, db_session_factory
) -> IdentitySyncService:
    identity_provider = ZitadelIdentityProviderPort(zitadel_orgs_adapter, db_session_factory)

    def uow_factory():
        return PostgresIdentitySyncUnitOfWork(db_session_factory)

    return IdentitySyncService(
        identity_provider=identity_provider,
        user_identity_provider=zitadel_users_adapter,
        uow_factory=uow_factory,
    )


async def test_identity_sync_service_tenant_provisioned(
    identity_sync_service: IdentitySyncService,
    db_session_factory,
    zitadel_orgs_adapter: ZitadelOrganizationsAdapter,
):
    # 1. Setup DbTenant
    tenant_id = generate_id("id")
    async with db_session_factory() as session:
        tenant = DbTenant(
            id=tenant_id,
            name="Test Sync Service Org",
            slug=f"sync-org-{tenant_id[:8]}",
            idp_tenant_id=None,
        )
        session.add(tenant)
        await session.commit()

    idp_tenant_id = None
    try:
        # 2. Invoke the service
        await identity_sync_service.handle_tenant_provisioned(tenant_id)

        # 3. Verify Local DB was updated
        async with db_session_factory() as session:
            updated_tenant = await session.get(DbTenant, tenant_id)
            assert updated_tenant is not None
            assert updated_tenant.idp_tenant_id is not None
            idp_tenant_id = updated_tenant.idp_tenant_id

    finally:
        # 4. Clean up the actual Zitadel Organization so it doesn't pollute the environment
        if idp_tenant_id:
            await zitadel_orgs_adapter.delete_organization(idp_tenant_id)


async def test_identity_sync_service_user_created(
    identity_sync_service: IdentitySyncService,
    db_session_factory,
    zitadel_orgs_adapter: ZitadelOrganizationsAdapter,
    zitadel_users_adapter: ZitadelUsersAdapter,
    zitadel_projects_adapter: ZitadelProjectsAdapter,
):
    # 1. Setup DbTenant and fully provision it
    tenant_id = generate_id("id")
    org_id, _ = await zitadel_orgs_adapter.create_organization("Test Sync Service User Org")

    try:
        user_id = generate_id("id")
        test_email = f"sync_test_{uuid.uuid4()}@example.com"

        async with db_session_factory() as session:
            tenant = DbTenant(
                id=tenant_id,
                name="Test Sync Service User Org",
                slug=f"sync-usr-{tenant_id[:8]}",
                idp_tenant_id=org_id,
            )
            session.add(tenant)

            user = DbUser(
                id=user_id,
                name="Sync Tester",
                email=test_email,
                idp_user_id=None,
            )
            session.add(user)
            await session.commit()

        # 2. Invoke handle_user_created
        await identity_sync_service.handle_user_created(
            user_id=user_id,
            tenant_id=tenant_id,
            email=test_email,
            first_name="Sync",
            last_name="Tester",
            role="TenantAdmin",
        )

        # 3. Verify Local DB
        async with db_session_factory() as session:
            updated_user = await session.get(DbUser, user_id)
            assert updated_user is not None
            assert updated_user.idp_user_id is not None
            idp_user_id = updated_user.idp_user_id

        # 4. Verify in Zitadel
        users = await zitadel_projects_adapter.get_users(org_id=org_id)
        found = next((u for u in users if u.id == idp_user_id), None)
        assert found is not None
        assert found.email == test_email

    finally:
        # Cleanup
        await zitadel_orgs_adapter.delete_organization(org_id)


async def test_identity_sync_service_app_subscribed_and_unsubscribed(
    identity_sync_service: IdentitySyncService,
    db_session_factory,
    zitadel_orgs_adapter: ZitadelOrganizationsAdapter,
    zitadel_projects_adapter: ZitadelProjectsAdapter,
):
    tenant_id = generate_id("id")
    org_id, _ = await zitadel_orgs_adapter.create_organization("Test Sync App Sub Org")

    try:
        async with db_session_factory() as session:
            tenant = DbTenant(
                id=tenant_id,
                name="Test Sync App Sub Org",
                slug=f"sync-app-{tenant_id[:8]}",
                idp_tenant_id=org_id,
            )
            session.add(tenant)
            await session.commit()

        # We use the UCP project ID for the test since we know it exists in the test environment
        idp_project_id = zitadel_projects_adapter.ucp_project_id

        # Subscribe
        await identity_sync_service.handle_app_subscribed(tenant_id, idp_project_id)

        # Verify grant exists
        search_data = await zitadel_projects_adapter._search_all(
            endpoint=f"/management/v1/projects/{idp_project_id}/grants/_search"
        )
        grant_exists = any(g.get("grantedOrgId") == org_id for g in search_data)
        assert grant_exists, "Project grant was not created in Zitadel"

        # Unsubscribe
        await identity_sync_service.handle_app_unsubscribed(tenant_id, idp_project_id)

        # Verify grant removed
        search_data_after = await zitadel_projects_adapter._search_all(
            endpoint=f"/management/v1/projects/{idp_project_id}/grants/_search"
        )
        grant_exists_after = any(g.get("grantedOrgId") == org_id for g in search_data_after)
        assert not grant_exists_after, "Project grant was not removed from Zitadel"

    finally:
        await zitadel_orgs_adapter.delete_organization(org_id)
