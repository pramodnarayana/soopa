import uuid

import pytest
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from platform_orm.models.identity import Role, Tenant, User, UserRole
from platform_orm.models.notifications import InAppNotification


@pytest.mark.asyncio
async def test_in_app_notifications_router_integration(db_session_factory):
    tenant_id = "test-router-tenant"
    user_id = "user-123"
    other_user_id = "user-456"
    notif_id = f"notif_inapp_{uuid.uuid4().hex}"
    other_user_notif_id = f"notif_inapp_{uuid.uuid4().hex}"

    # Setup test DB
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

        user_model = User(id=user_id, email="testapi@test.com", name="API User")
        session.add(user_model)

        other_user_model = User(id=other_user_id, email="other@test.com", name="Other User")
        session.add(other_user_model)

        await session.flush()

        role = Role(
            id=f"rol_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            name="TenantAdmin",
            description="Admin role",
            capabilities=["users:write"],
        )
        session.add(role)
        await session.flush()

        tenant_user = UserRole(
            id=f"urol_{uuid.uuid4().hex}", tenant_id=tenant_id, user_id=user_id, role_id=role.id
        )
        session.add(tenant_user)

        other_tenant_user = UserRole(
            id=f"urol_{uuid.uuid4().hex}",
            tenant_id=tenant_id,
            user_id=other_user_id,
            role_id=role.id,
        )
        session.add(other_tenant_user)

        notification = InAppNotification(
            id=notif_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Router Test",
            body="Content",
            is_read=False,
        )
        session.add(notification)

        # Add notification for other user (same tenant, different user)
        other_user_notification = InAppNotification(
            id=other_user_notif_id,
            tenant_id=tenant_id,
            user_id=other_user_id,
            title="Other User Notification",
            body="Other Content",
            is_read=False,
        )
        session.add(other_user_notification)

    from fastapi import FastAPI

    from notification.api.in_app_notifications_router import router
    from notification.bootstrap.container import Container

    app = FastAPI()

    class MockIdentity:
        def __init__(self, subject, authorized_tenants):
            self.subject = subject
            self.authorized_tenants = authorized_tenants

    @app.middleware("http")
    async def mock_identity_middleware(request, call_next):
        # Skip identity assignment if unauthenticated scenario requested
        if request.headers.get("X-Test-Unauthenticated"):
            return await call_next(request)
        # We can dynamically set the identity based on headers if needed,
        # but for now we'll just set it to the test user and tenant.
        tenant_context = request.headers.get("x-mock-tenant", tenant_id)
        user_context = request.headers.get("x-mock-user", user_id)
        request.state.identity = MockIdentity(
            subject=user_context, authorized_tenants={tenant_context}
        )
        return await call_next(request)

    app.include_router(router)

    # Initialize container and override query repository
    container = Container()

    from notification.adapters.outbound.postgres_notification_query_repository import (
        SqlAlchemyNotificationQueryRepository,
    )

    repo_instance = SqlAlchemyNotificationQueryRepository(db_session_factory)

    from tests.fakes import FakeStreamManager

    fake_stream = FakeStreamManager()

    container.query_repository.override(providers.Object(repo_instance))
    container.stream_manager.override(providers.Object(fake_stream))
    container.wire(modules=["notification.api.in_app_notifications_router"])

    try:
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

            # Try to mark another user's notification as read (same tenant, different user)
            cross_user_notif_response = await ac.put(
                f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/{other_user_notif_id}/read"
            )
            assert cross_user_notif_response.status_code == 404

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

            # Unauthenticated scenario: Request without identity should return 401
            unauth_response = await ac.get(
                f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app",
                headers={"X-Test-Unauthenticated": "true"},
            )
            assert unauth_response.status_code == 401

            # Unauthenticated scenario for mark-as-read endpoint
            unauth_put_response = await ac.put(
                f"/api/v1/notifications/{tenant_id}/users/{user_id}/in-app/{notif_id}/read",
                headers={"X-Test-Unauthenticated": "true"},
            )
            assert unauth_put_response.status_code == 401
    finally:
        # Clean up container overrides and unwire
        container.query_repository.reset_override()
        container.stream_manager.reset_override()
        container.unwire()
