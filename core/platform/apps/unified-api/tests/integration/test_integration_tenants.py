import httpx
import pytest


@pytest.mark.asyncio
async def test_get_tenant_by_id(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == tenant_id


@pytest.mark.asyncio
async def test_update_tenant(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/name", json={"name": "Updated Tenant Name"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated Tenant Name"
