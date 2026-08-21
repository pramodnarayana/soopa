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
        id="tenant_test_123",
        name="Test Tenant",
        slug="test-tenant",
        idp_tenant_id="mock_org_id",
    )
    db_session.add(tenant)
    await db_session.commit()

    payload = {
        "email": "integration@test.com",
        "first_name": "Integration",
        "last_name": "Test",
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
    assert user_record.email == "integration@test.com"
    assert user_record.name == "Integration Test"

    # Check outbox event was emitted (UserCreatedEvent)
    outbox_result = await db_session.execute(
        text("SELECT event_type FROM platform.outbox_messages WHERE aggregate_id = :user_id"),
        {"user_id": user_id},
    )
    events = [row.event_type for row in outbox_result.fetchall()]
    assert "UserCreatedEvent" in events
