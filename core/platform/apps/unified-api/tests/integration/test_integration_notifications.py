import httpx
import pytest


@pytest.mark.asyncio
async def test_get_notifications(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "usr_platform_admin_123"
    response = await auth_client.get(f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_mark_notification_read(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "usr_platform_admin_123"
    response = await auth_client.put(
        f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/notif_123/read"
    )
    assert response.status_code == 404, response.text
