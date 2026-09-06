from datetime import UTC, datetime

import pytest
from seedwork import generate_id
from ucp_models.subscriptions import App

from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.domain.constants import LifecycleStatus
from ucp.domain.models.tenant import Tenant, TenantSubscription

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_save_and_find_tenant(db_session):
    # Setup Apps
    app1 = App(id="app_1", name="App 1", slug="app-1")
    app2 = App(id="app_2", name="App 2", slug="app-2")
    db_session.add(app1)
    db_session.add(app2)
    await db_session.flush()

    repo = TenantRepository(db_session)

    tenant_id = generate_id("ten")
    tenant = Tenant(
        id=tenant_id,
        name="Integration Test Tenant",
        slug=f"integ-{tenant_id}",
        idp_tenant_id=f"idp-{tenant_id}",
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        subscriptions=[
            TenantSubscription(app_id="app_1", status=LifecycleStatus.ACTIVE),
            TenantSubscription(app_id="app_2", status=LifecycleStatus.INACTIVE),
        ],
    )

    # Save the tenant
    await repo.save(tenant)
    await db_session.flush()

    # Find by ID
    found_tenant = await repo.find_by_id(tenant_id)
    assert found_tenant is not None
    assert found_tenant.id == tenant_id
    assert found_tenant.name == "Integration Test Tenant"
    assert found_tenant.status == LifecycleStatus.ACTIVE

    assert len(found_tenant.subscriptions) == 2
    sub_map = {s.app_id: s.status for s in found_tenant.subscriptions}
    assert sub_map["app_1"] == LifecycleStatus.ACTIVE
    assert sub_map["app_2"] == LifecycleStatus.INACTIVE

    # Find by IDP tenant ID
    found_tenant_idp = await repo.find_by_idp_tenant_id(f"idp-{tenant_id}")
    assert found_tenant_idp is not None
    assert found_tenant_idp.id == tenant_id

    # Test find_all includes this tenant
    all_tenants = await repo.find_all()
    assert any(t.id == tenant_id for t in all_tenants)
