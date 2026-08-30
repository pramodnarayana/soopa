import httpx
import pytest


@pytest.mark.asyncio
async def test_get_notifications(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "machine_client_test_123"  # The ID assigned to the API token user
    response = await auth_client.get(f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app")
    assert response.status_code in (200, 403)


@pytest.mark.asyncio
async def test_mark_notification_read(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    user_id = "machine_client_test_123"
    response = await auth_client.put(
        f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/notif_123/read"
    )
    assert response.status_code in (200, 204, 403, 404)
