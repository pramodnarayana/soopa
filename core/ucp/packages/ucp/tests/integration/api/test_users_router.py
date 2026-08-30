import uuid

import pytest
from database.models.identity import Tenant as OrmTenant
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_user_endpoint_resolves_di_and_persists(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Validates that the users router correctly injects the CreateUserUseCase
    from the dependency injection container and persists the user to the database,
    emitting the outbox event successfully without raising IDP-related DI errors.
    """
    # 1. Arrange: Create a Tenant to associate the user with
    async with db_session.begin():
        tenant = OrmTenant(
            id=f"ten_{uuid.uuid4().hex[:12]}",
            name=f"Test Tenant {uuid.uuid4().hex[:8]}",
            slug=f"test-tenant-{uuid.uuid4().hex[:8]}",
            idp_tenant_id=f"mock_org_{uuid.uuid4().hex[:8]}",
        )
        db_session.add(tenant)
        # Ensure the 'TenantAdmin' role exists (in case other tests cleared it)
        await db_session.execute(
            text(
                "INSERT INTO identity.tenants (id, name, slug, idp_tenant_id, status, created_at, updated_at) "
                "VALUES ('ten_000000000000000000000000', 'Global', 'global', 'global', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT DO NOTHING"
            )
        )
        await db_session.execute(
            text(
                "INSERT INTO identity.roles (id, tenant_id, name, description, capabilities, created_at, updated_at) "
                "VALUES ('rol_a62f2225bf70bfac', 'ten_000000000000000000000000', 'TenantAdmin', 'Tenant admin', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT DO NOTHING"
            )
        )

    payload = {
        "email": f"integration_{uuid.uuid4().hex[:8]}@test.com",
        "firstName": "Integration",
        "lastName": "Test",
        "role": "TenantAdmin",
    }

    # 2. Act: Call the endpoint
    response = await client.post(
        f"/api/v1/tenants/{tenant.id}/users",
        json=payload,
    )

    # 3. Assert: Verify the DI container resolved and the endpoint succeeded
    if response.status_code != 200:
        print(f"DEBUG RESPONSE: {response.json()}")
    assert response.status_code == 200
    data = response.json()
    assert "userId" in data

    # 4. Assert: Verify database state
    user_id = data["userId"]

    # Check User was saved
    result = await db_session.execute(
        text("SELECT email, name FROM identity.users WHERE id = :user_id"), {"user_id": user_id}
    )
    user_record = result.fetchone()
    assert user_record is not None
    assert user_record.email.startswith("integration_")
    assert user_record.name == "Integration Test"

    # Check outbox event was emitted (UserCreatedEvent)
    outbox_result = await db_session.execute(
        text("SELECT event_type FROM identity.outbox WHERE payload->>'user_id' = :user_id"),
        {"user_id": user_id},
    )
    events = [row.event_type for row in outbox_result.fetchall()]
    assert "UserInvited" in events
