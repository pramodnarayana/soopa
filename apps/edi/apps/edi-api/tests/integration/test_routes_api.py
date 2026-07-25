import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

async def test_create_and_get_inbound_route(client: AsyncClient):
    payload = {
        "as2_partner_id": str(uuid.uuid4()), # Should trigger FK constraint error if checked by DB
        "sftp_partner_id": None,
        "transaction_type": "850",
        "description": "Integration Test Inbound Route",
        "active": True
    }

    response = await client.post("/api/v1/routes/inbound", json=payload)
    print("Inbound Route Create Response:", response.text)

async def test_create_and_get_outbound_route(client: AsyncClient):
    payload = {
        "as2_partner_id": str(uuid.uuid4()), # Should trigger FK constraint error if checked by DB
        "transaction_type": "855",
        "description": "Integration Test Outbound Route",
        "active": True
    }

    response = await client.post("/api/v1/routes/outbound", json=payload)
    print("Outbound Route Create Response:", response.text)
