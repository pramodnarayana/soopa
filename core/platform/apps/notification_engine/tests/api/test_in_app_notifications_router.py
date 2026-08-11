import uuid

import pytest
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from platform_orm.models.identity import Tenant, TenantUser, User
from platform_orm.models.notifications import InAppNotification


@pytest.mark.asyncio
async def test_in_app_notifications_router_integration(db_session_factory):
    tenant_id = "test-router-tenant"
    user_id = "user-123"
    notif_id = f"notif_inapp_{uuid.uuid4().hex}"

    # Setup test DB
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            status="ACTIVE",
        )
        session.add(tenant)

        user_model = User(id=user_id, email="testapi@test.com", name="API User")
        session.add(user_model)

        await session.flush()

        tenant_user = TenantUser(tenant_id=tenant_id, user_id=user_id, role="admin", active=True)
        session.add(tenant_user)

        notification = InAppNotification(
            id=notif_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Router Test",
            body="Content",
            is_read=False,
        )
        session.add(notification)

    from fastapi import FastAPI

    from notification_engine.api.in_app_notifications_router import router
    from notification_engine.bootstrap.container import Container

    app = FastAPI()

    class MockIdentity:
        def __init__(self, user_id, authorized_tenants):
            self.user_id = user_id
            self.authorized_tenants = authorized_tenants

    @app.middleware("http")
    async def mock_identity_middleware(request, call_next):
        # We can dynamically set the identity based on headers if needed,
        # but for now we'll just set it to the test user and tenant.
        tenant_context = request.headers.get("x-mock-tenant", tenant_id)
        user_context = request.headers.get("x-mock-user", user_id)
        request.state.identity = MockIdentity(
            user_id=user_context, authorized_tenants={tenant_context}
        )
        return await call_next(request)

    app.include_router(router)

    # Initialize container and override query repository
    container = Container()

    from notification_engine.adapters.outbound.postgres_notification_query_repository import (
        PostgresNotificationQueryRepository,
    )

    repo_instance = PostgresNotificationQueryRepository(db_session_factory)

    # Mock stream manager for SSE endpoint
    from unittest.mock import MagicMock

    mock_stream = MagicMock()

    container.query_repository.override(providers.Object(repo_instance))
    container.stream_manager.override(providers.Object(mock_stream))
    container.wire(modules=["notification_engine.api.in_app_notifications_router"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Get notifications
        response = await ac.get(f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == notif_id
        assert data[0]["title"] == "Router Test"
        assert data[0]["is_read"] is False

        # Mark read
        put_response = await ac.put(
            f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/{notif_id}/read"
        )
        assert put_response.status_code == 200

        # Verify it was marked read
        response2 = await ac.get(f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app")
        data2 = response2.json()
        assert data2[0]["is_read"] is True

        # Try non-existent
        bad_response = await ac.put(
            f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/wrong_id/read"
        )
        assert bad_response.status_code == 404

        # Cross-tenant authorization scenario: Request tenant B's path while authenticated as tenant A
        cross_tenant_response = await ac.get(
            f"/api/v1/notifications/other-tenant-id/users/{user_id}/in-app",
            headers={"x-mock-tenant": tenant_id},  # Authenticated for test-router-tenant
        )
        assert cross_tenant_response.status_code == 403

        # Cross-user authorization scenario: Request user B's path while authenticated as user A
        cross_user_response = await ac.get(
            f"/api/v1/notifications/{tenant_id}/users/other-user-id/in-app",
            headers={"x-mock-user": user_id},  # Authenticated for user-123
        )
        assert cross_user_response.status_code == 403
