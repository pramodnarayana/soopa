import httpx
import pytest


@pytest.mark.asyncio
async def test_tenants_full_crud(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    """
    Test the full lifecycle of a tenant, including apps and subscriptions,
    using a PLATFORM_ADMIN identity (patched in conftest).
    """
    # 1. List tenants (should return at least the seeded tenant)
    res = await auth_client.get("/api/v1/tenants")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    assert len(data["items"]) > 0

    # 2. Get roles
    res = await auth_client.get("/api/v1/tenants/roles")
    assert res.status_code == 200
    roles = res.json()
    assert len(roles) > 0

    # 3. Provision a new tenant
    res = await auth_client.post("/api/v1/tenants", json={"name": "Integration Test Tenant"})
    assert res.status_code == 200
    new_tenant = res.json()
    tenant_id = new_tenant["id"]
    assert new_tenant["name"] == "Integration Test Tenant"

    # 4. Get the new tenant by ID
    res = await auth_client.get(f"/api/v1/tenants/{tenant_id}")
    assert res.status_code == 200
    assert res.json()["id"] == tenant_id

    # 5. Update tenant name
    res = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/name", json={"name": "Updated Test Tenant"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Test Tenant"

    # 6. List apps (to get an app ID for subscription)
    res = await auth_client.get("/api/v1/apps")
    assert res.status_code == 200
    apps = res.json()
    if len(apps) > 0:
        app_id = apps[0]["id"]

        # 7. Subscribe to app
        res = await auth_client.post(
            f"/api/v1/tenants/{tenant_id}/subscriptions", json={"appId": app_id}
        )
        assert res.status_code == 200

        # 8. Get subscriptions
        res = await auth_client.get(f"/api/v1/tenants/{tenant_id}/subscriptions")
        assert res.status_code == 200
        assert len(res.json()) > 0

        # 9. Unsubscribe from app
        res = await auth_client.delete(f"/api/v1/tenants/{tenant_id}/subscriptions/{app_id}")
        assert res.status_code == 200

    # 10. Update tenant status to inactive
    res = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/status", json={"status": "inactive"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "inactive"

    # 11. Delete tenant
    res = await auth_client.delete(f"/api/v1/tenants/{tenant_id}")
    assert res.status_code == 204

    # 12. Confirm deletion
    res = await auth_client.get(f"/api/v1/tenants/{tenant_id}")
    assert res.status_code == 404
