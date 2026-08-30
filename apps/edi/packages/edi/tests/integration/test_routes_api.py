import pytest
from httpx import AsyncClient
from seedwork import generate_id

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_and_get_inbound_route(client: AsyncClient):
    payload = {
        "as2_partner_id": generate_id("id"),  # Should trigger FK constraint error if checked by DB
        "sftp_partner_id": None,
        "transaction_type": "850",
        "description": "Integration Test Inbound Route",
        "active": True,
    }

    response = await client.post("/api/v1/tenants/1/edi/routes/inbound", json=payload)
    # FK constraint error should return 400 or 422 (client error), not 500
    assert response.status_code in (400, 422), (
        f"Expected FK constraint error, got {response.status_code}: {response.text}"
    )


async def test_create_and_get_outbound_route(client: AsyncClient):
    payload = {
        "as2_partner_id": generate_id("id"),  # Should trigger FK constraint error if checked by DB
        "transaction_type": "855",
        "description": "Integration Test Outbound Route",
        "active": True,
    }

    response = await client.post("/api/v1/tenants/1/edi/routes/outbound", json=payload)
    # FK constraint error should return 400 or 422 (client error), not 500
    assert response.status_code in (400, 422), (
        f"Expected FK constraint error, got {response.status_code}: {response.text}"
    )
