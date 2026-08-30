import httpx
import pytest


@pytest.mark.asyncio
async def test_get_webhooks(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/webhooks")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_create_webhook(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/webhooks",
        json={
            "name": "Integration Test Webhook",
            "url": "https://example.com/webhook",
            "events": ["edi.transaction.created"],
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_get_webhook_by_id(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/webhooks/wh_123")
    assert response.status_code == 404, response.text
