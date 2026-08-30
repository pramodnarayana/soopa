import pytest
from seedwork import generate_random_hex

pytestmark = pytest.mark.integration
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_provision_and_get_tenant(client: AsyncClient) -> "Any":
    # Provision
    name = f"Integration Test Tenant {generate_random_hex(6)}"
    response = await client.post("/api/v1/tenants", json={"name": name})
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == name
    assert data["id"].startswith("ten_")
    assert data["status"] == "active"

    tenant_id = data["id"]

    # Get All
    response = await client.get("/api/v1/tenants")
    assert response.status_code == 200
    tenants_response = response.json()
    assert any(t["id"] == tenant_id for t in tenants_response["items"])

    # Get One
    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tenant_id


@pytest.mark.asyncio
async def test_update_tenant_name(client: AsyncClient) -> "Any":
    # Provision
    old_name = f"Old Name {generate_random_hex(6)}"
    new_name = f"New Name {generate_random_hex(6)}"
    response = await client.post("/api/v1/tenants", json={"name": old_name})
    tenant_id = response.json()["id"]

    # Update Name
    response = await client.patch(f"/api/v1/tenants/{tenant_id}/name", json={"name": new_name})
    assert response.status_code == 200
    assert response.json()["name"] == new_name

    # Verify
    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.json()["name"] == new_name


@pytest.mark.asyncio
async def test_delete_tenant(client: AsyncClient) -> "Any":
    # Provision
    name = f"To Delete {generate_random_hex(6)}"
    response = await client.post("/api/v1/tenants", json={"name": name})
    tenant_id = response.json()["id"]

    # Delete
    response = await client.delete(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 204

    # Verify it's gone
    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 404
