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
from database.models.identity import IdentityOutbox, User
from identity.domain.constants import IdentityEventType
from sqlalchemy import select


@pytest.mark.asyncio
async def test_get_users(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/users")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_create_user(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict,
    db_session_factory: Callable,
):
    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "email": "integration_test@example.com",
            "firstName": "Integration",
            "lastName": "Test",
            "role": "rol_a62f2225bf70bfac",
        },
    )
    assert response.status_code in (200, 201), response.text
    response_data = response.json()
    assert "userId" in response_data
    user_id = response_data["userId"]

    # Enterprise Standard: Assert database and outbox states via Narrow Integration Test
    async with db_session_factory() as session:
        # 1. Assert user was physically created in the DB
        db_user = await session.get(User, user_id)
        assert db_user is not None
        assert db_user.email == "integration_test@example.com"

        # 2. Assert exactly ONE Outbox event was emitted (to prevent race conditions with redundant events)
        outbox_stmt = select(IdentityOutbox).where(
            IdentityOutbox.payload["user_id"].astext == user_id,
        )
        outbox_events = (await session.scalars(outbox_stmt)).all()
        assert len(outbox_events) == 1, (
            f"Expected exactly 1 event, but got {len(outbox_events)}: {[e.event_type for e in outbox_events]}"
        )

        event = outbox_events[0]
        assert event.event_type == IdentityEventType.USER_INVITED
        assert event.payload["email"] == "integration_test@example.com"
        assert event.payload["role"] == "TenantAdmin"


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
            "role": "rol_a62f2225bf70bfac",
        },
    )
    assert res.status_code in (200, 201), res.text
    user_id = res.json()["userId"]

    # 2. Simulate the identity worker binding the IDP user ID (domain pathway, not raw SQL)
    await simulate_idp_provisioning(user_id)

    # 3. Update the user — requires idp_user_id to be set
    response = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/users/{user_id}",
        json={"firstName": "Updated", "lastName": "Name", "role": "rol_a62f2225bf70bfac"},
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
            "role": "rol_a62f2225bf70bfac",
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
            "role": "rol_a62f2225bf70bfac",
        },
    )
    assert res.status_code in (200, 201), res.text
    user_id = res.json()["userId"]

    await simulate_idp_provisioning(user_id)

    response = await auth_client.delete(f"/api/v1/tenants/{tenant_id}/users/{user_id}")
    assert response.status_code in (200, 204), response.text
