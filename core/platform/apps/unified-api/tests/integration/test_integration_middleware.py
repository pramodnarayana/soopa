import httpx
import pytest


@pytest.mark.asyncio
async def test_authentication_middleware_rejects_unauthenticated(client: httpx.AsyncClient):
    # Any protected endpoint should return 401 if no auth is provided
    response = await client.get("/api/v1/tenants/ten_123/users")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.asyncio
async def test_authentication_middleware_accepts_valid_token(
    auth_client: httpx.AsyncClient, seeded_api_token: dict
):
    # This should pass authentication, but might return 403 or 404 depending on tenant context
    tenant_id = seeded_api_token["tenant_id"]

    # We will test fetching a user for the tenant. It shouldn't return 401.
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/users")
    assert response.status_code != 401
