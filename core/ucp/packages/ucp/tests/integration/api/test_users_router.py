import uuid

import pytest
from httpx import AsyncClient
from platform_orm.models.identity import Tenant as OrmTenant
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
    tenant = OrmTenant(
        id=f"ten_{uuid.uuid4().hex[:12]}",
        name=f"Test Tenant {uuid.uuid4().hex[:8]}",
        slug=f"test-tenant-{uuid.uuid4().hex[:8]}",
        idp_tenant_id=f"mock_org_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(tenant)
    await db_session.commit()

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
    assert response.status_code == 200
    data = response.json()
    assert "userId" in data

    # 4. Assert: Verify database state
    user_id = data["userId"]

    # Check User was saved
    result = await db_session.execute(
        text("SELECT email, name FROM ucp.users WHERE id = :user_id"), {"user_id": user_id}
    )
    user_record = result.fetchone()
    assert user_record is not None
    assert user_record.email.startswith("integration_")
    assert user_record.name == "Integration Test"

    # Check outbox event was emitted (UserCreatedEvent)
    outbox_result = await db_session.execute(
        text("SELECT event_type FROM platform.outbox_messages WHERE aggregate_id = :user_id"),
        {"user_id": user_id},
    )
    events = [row.event_type for row in outbox_result.fetchall()]
    assert "UserCreatedEvent" in events
