"""
Integration tests for the Users API router.

Architecture note on IDP provisioning:
    In production, CreateUserUseCase creates a local user record with idp_user_id=None.
    The identity worker subsequently consumes the `user_created` outbox event, provisions
    the user in the IdP (e.g. Zitadel), and then writes back the idp_user_id via
    PostgresUserRepository.save().

    Tests that exercise flows requiring an existing IDP mapping (update_user, toggle_status,
    delete_user) use the `simulate_idp_provisioning` fixture, which mirrors this exact
    domain pathway — using PostgresUserRepository.find_by_id() + User.set_idp_user_id()
    + PostgresUserRepository.save() — rather than raw SQL.
"""

from collections.abc import Callable, Coroutine

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_users(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/users")
    assert response.status_code in (200, 403)


@pytest.mark.asyncio
async def test_create_user(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "email": "integration_test@example.com",
            "firstName": "Integration",
            "lastName": "Test",
            "role": "admin",
        },
    )
    assert response.status_code in (200, 201), response.text
    assert "userId" in response.json()


@pytest.mark.asyncio
async def test_update_user(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict,
    simulate_idp_provisioning: Callable[[str], Coroutine],
):
    """
    Creates a user, simulates the identity worker registering an IDP user ID via
    the domain repository, then calls the update endpoint.
    """
    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create user (idp_user_id is None at this point — as in production)
    res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "email": "update_test@example.com",
            "firstName": "First",
            "lastName": "Last",
            "role": "admin",
        },
    )
    assert res.status_code in (200, 201), res.text
    user_id = res.json()["userId"]

    # 2. Simulate the identity worker binding the IDP user ID (domain pathway, not raw SQL)
    await simulate_idp_provisioning(user_id)

    # 3. Update the user — requires idp_user_id to be set
    response = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/users/{user_id}",
        json={"firstName": "Updated", "lastName": "Name", "role": "admin"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_toggle_user_status(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict,
    simulate_idp_provisioning: Callable[[str], Coroutine],
):
    """
    Creates a user, provisions IDP mapping via the domain layer, then toggles status.
    """
    tenant_id = seeded_api_token["tenant_id"]

    res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "email": "toggle_test@example.com",
            "firstName": "First",
            "lastName": "Last",
            "role": "admin",
        },
    )
    assert res.status_code in (200, 201), res.text
    user_id = res.json()["userId"]

    await simulate_idp_provisioning(user_id)

    response = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/users/{user_id}/status",
        json={"action": "deactivate"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_delete_user(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict,
    simulate_idp_provisioning: Callable[[str], Coroutine],
):
    """
    Creates a user, provisions IDP mapping via the domain layer, then deletes the user.
    """
    tenant_id = seeded_api_token["tenant_id"]

    res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "email": "delete_test@example.com",
            "firstName": "First",
            "lastName": "Last",
            "role": "admin",
        },
    )
    assert res.status_code in (200, 201), res.text
    user_id = res.json()["userId"]

    await simulate_idp_provisioning(user_id)

    response = await auth_client.delete(f"/api/v1/tenants/{tenant_id}/users/{user_id}")
    assert response.status_code in (200, 204), response.text
