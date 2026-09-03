import httpx
import pytest


@pytest.mark.asyncio
async def test_get_trading_partners(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/trading-partners")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_get_trading_partner_by_id(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/trading-partners/tp_123")
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_get_transactions(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/transactions/messages")
    assert response.status_code == 200, response.text
