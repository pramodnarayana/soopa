from datetime import UTC, datetime

import pytest
from database.exceptions import DuplicateEntityError
from seedwork import generate_id
from ucp_models.subscriptions import App

from ucp.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from ucp.domain.constants import LifecycleStatus
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.tenant import Tenant, TenantSubscription

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_save_and_find_tenant(db_session):
    # Setup Apps
    app1 = App(id="app_1", name="App 1", slug="app-1")
    app2 = App(id="app_2", name="App 2", slug="app-2")
    db_session.add(app1)
    db_session.add(app2)
    await db_session.flush()

    repo = SqlAlchemyTenantRepository(db_session)

    tenant_id = generate_id(DomainIdPrefix.TENANT.value)
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


@pytest.mark.asyncio
async def test_insert_if_slug_available_handles_slug_conflict_and_preserves_name_uniqueness(
    db_session,
) -> None:
    repo = SqlAlchemyTenantRepository(db_session)
    slug = f"slug-check-{generate_id(DomainIdPrefix.TENANT.value)}"

    first = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT.value),
        name=f"Acme, Corp. {slug}",
        slug=slug,
        idp_tenant_id=None,
    ).unwrap()
    assert await repo.insert_if_slug_available(first) is True

    # Slug collision with distinct name returns False cleanly without aborting transaction
    slug_collision = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT.value),
        name=f"Acme Corp {slug}",
        slug=slug,
        idp_tenant_id=None,
    ).unwrap()
    assert await repo.insert_if_slug_available(slug_collision) is False

    # Subsequent query in the exact same transaction succeeds
    retry = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT.value),
        name=f"Acme Corp {slug}",
        slug=f"{slug}-2",
        idp_tenant_id=None,
    ).unwrap()
    assert await repo.insert_if_slug_available(retry) is True

    # Duplicate name with distinct slug still raises DuplicateEntityError
    duplicate_name = Tenant.create(
        id=generate_id(DomainIdPrefix.TENANT.value),
        name=first.name,
        slug=f"{slug}-3",
        idp_tenant_id=None,
    ).unwrap()
    with pytest.raises(DuplicateEntityError):
        await repo.insert_if_slug_available(duplicate_name)
