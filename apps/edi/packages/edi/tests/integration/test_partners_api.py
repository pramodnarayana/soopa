import pytest
from httpx import AsyncClient
from seedwork import generate_id

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_and_get_sftp_partner(client: AsyncClient):
    # Test creating a partner
    payload = {
        "name": "Integration Test SFTP",
        "host": "sftp.example.com",
        "port": 22,
        "username": "user123",
        "password": "password123",
        "active": True,
    }

    response = await client.post("/api/v1/tenants/1/edi/trading-partners/sftp", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert "id" in data
    partner_id = data["id"]

    # Test getting the partner back
    response = await client.get("/api/v1/tenants/1/edi/trading-partners")
    assert response.status_code == 200, response.text
    fetched_list = response.json()
    fetched = next((p for p in fetched_list if p["id"] == partner_id), None)
    assert fetched is not None

    assert fetched["name"] == payload["name"]
    assert fetched["host"] == payload["host"]

    # Check that database constraint errors are caught
    # Try creating with missing required fields to trigger DB constraint errors
    # instead of passing purely by Pydantic (though Pydantic should catch some, DB is ultimate truth)
    bad_payload = {
        "name": "Bad SFTP Partner",
        # Missing host which is probably required
        "port": 22,
    }
    response = await client.post("/api/v1/tenants/1/edi/trading-partners/sftp", json=bad_payload)
    assert response.status_code == 422  # Pydantic validation error


async def test_create_and_get_as2_partner(platform_client: AsyncClient):
    payload = {
        "name": "Integration Test AS2",
        "as2_id": "AS2_TEST_" + generate_id("id")[:8],
        "is_local": True,
        "url": "http://example.com/as2",
    }

    response = await platform_client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners", json=payload
    )
    assert response.status_code == 201, f"Failed to create AS2 partner: {response.text}"
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["as2_id"] == payload["as2_id"]

    # Get all AS2 partners
    list_res = await platform_client.get("/api/v1/platform/trading-partners/as2/trading-partners")
    assert list_res.status_code == 200
    partners = list_res.json()
    assert any(p["id"] == data["id"] for p in partners)

    # Test rotate certificates
    rotate_res = await platform_client.put(
        f"/api/v1/platform/trading-partners/as2/certificates/{data['id']}/rotate",
        json={"action": "generate"},
    )
    assert rotate_res.status_code == 200

    # Test export certificates
    export_res = await platform_client.get(
        f"/api/v1/platform/trading-partners/as2/certificates/{data['id']}/export"
    )
    assert export_res.status_code == 200
    export_data = export_res.json()
    assert "public_cert_pem" in export_data
