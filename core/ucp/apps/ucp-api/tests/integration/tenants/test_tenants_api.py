from typing import Any
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_provision_and_get_tenant(client: AsyncClient) -> "Any":
    # Provision
    response = await client.post("/api/v1/tenants/", json={"name": "Integration Test Tenant"})
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Integration Test Tenant"
    assert data["id"].startswith("ten_")
    assert data["idp_tenant_id"] == "mock-org-123"
    assert data["status"] == "active"

    tenant_id = data["id"]

    # Get All
    response = await client.get("/api/v1/tenants/")
    assert response.status_code == 200
    tenants = response.json()
    assert len(tenants) == 1
    assert tenants[0]["id"] == tenant_id

    # Get One
    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tenant_id


@pytest.mark.asyncio
async def test_update_tenant_name(client: AsyncClient) -> "Any":
    # Provision
    response = await client.post("/api/v1/tenants/", json={"name": "Old Name"})
    tenant_id = response.json()["id"]

    # Update Name
    response = await client.patch(f"/api/v1/tenants/{tenant_id}/name", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"

    # Verify
    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_tenant(client: AsyncClient) -> "Any":
    # Provision
    response = await client.post("/api/v1/tenants/", json={"name": "To Delete"})
    tenant_id = response.json()["id"]

    # Delete
    response = await client.delete(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify it's gone
    response = await client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 404
