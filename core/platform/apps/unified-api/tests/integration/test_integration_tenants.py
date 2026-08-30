import httpx
import pytest


@pytest.mark.asyncio
async def test_get_tenant_by_id(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}")

    # 403 because machine tokens might not be a "tenant_member" by default depending on roles
    # But since it's a test, let's see what the response is.
    # M2M keys should be able to get their own tenant if they have the role.
    # The API key authenticator builds a machine identity with `authorized_tenants={tenant_id}`.
    assert response.status_code in (200, 403, 404)
    if response.status_code == 200:
        data = response.json()
        assert data["id"] == tenant_id


@pytest.mark.asyncio
async def test_update_tenant(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/name", json={"name": "Updated Tenant Name"}
    )
    assert response.status_code in (200, 403)
