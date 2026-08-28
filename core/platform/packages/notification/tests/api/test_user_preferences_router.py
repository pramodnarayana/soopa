import pytest
from httpx import ASGITransport, AsyncClient

from notification.application.update_user_preference_use_case import UpdateUserPreferenceUseCase
from notification.domain.models import Channel, UserNotificationPreference


@pytest.mark.asyncio
async def test_user_preferences_router():
    tenant_id = "test-tenant-123"
    user_id = "test-user-123"

    from dependency_injector import providers
    from fastapi import FastAPI
    from unified_api.adapters.inbound.http.routers.notification_user_preferences_router import (
        router,
    )

    from notification.bootstrap.container import Container

    app = FastAPI()

    class MockIdentity:
        def __init__(self, user_id, authorized_tenants):
            self.user_id = user_id
            self.subject = user_id
            self.authorized_tenants = authorized_tenants

    @app.middleware("http")
    async def mock_identity_middleware(request, call_next):
        tenant_context = request.headers.get("x-mock-tenant", tenant_id)
        user_context = request.headers.get("x-mock-user", user_id)
        request.state.identity = MockIdentity(
            user_id=user_context, authorized_tenants={tenant_context}
        )
        return await call_next(request)

    app.include_router(router)

    container = Container()

    from notification.application.get_user_preferences_use_case import GetUserPreferencesUseCase
    from tests.fakes import FakeNotificationUow, FakeUserPrefRepo

    # Use the real use case backed by our Fake repository
    fake_repo = FakeUserPrefRepo()
    uow = FakeNotificationUow(
        user_preference_repo=fake_repo,
        template_repo=None,
        record_repo=None,
        route_repo=None,
        outbox_repo=None,
    )
    real_update_use_case = UpdateUserPreferenceUseCase(uow=uow)
    real_get_use_case = GetUserPreferencesUseCase(uow=uow)

    # Seed the fake repository for the GET test
    expected_pref = UserNotificationPreference(
        id="notif_pref_123",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="invoice.payment_failed",
        channel=Channel.EMAIL,
        is_enabled=False,
    )
    fake_repo.prefs[(tenant_id, user_id, "invoice.payment_failed", "EMAIL")] = expected_pref

    container.update_user_preference_use_case.override(providers.Object(real_update_use_case))
    container.get_user_preferences_use_case.override(providers.Object(real_get_use_case))
    container.wire(
        modules=["unified_api.adapters.inbound.http.routers.notification_user_preferences_router"]
    )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. GET preferences
            response = await ac.get(f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["is_enabled"] is False

            # 2. PATCH preference
            response = await ac.patch(
                f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences/invoice.payment_failed/EMAIL",
                json={"is_enabled": True},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["is_enabled"] is True
            # Verify it was updated in our fake DB
            updated_pref = fake_repo.prefs[(tenant_id, user_id, "invoice.payment_failed", "EMAIL")]
            assert updated_pref.is_enabled is True

            # 3. PATCH with invalid channel (Validation Error handled by FastAPI)
            response = await ac.patch(
                f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences/invoice.payment_failed/INVALID",
                json={"is_enabled": True},
            )
            assert response.status_code == 422

            # 4. GET with different user in x-mock-user header (IDOR test - same tenant)
            different_user = "different-user-456"
            response = await ac.get(
                f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences",
                headers={"x-mock-user": different_user},
            )
            assert response.status_code == 403

            # 5. PATCH with different user in x-mock-user header (IDOR test - same tenant)
            response = await ac.patch(
                f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences/invoice.payment_failed/EMAIL",
                json={"is_enabled": False},
                headers={"x-mock-user": different_user},
            )
            assert response.status_code == 403

            # Verify the unauthorized PATCH didn't affect the data
            final_pref = fake_repo.prefs[(tenant_id, user_id, "invoice.payment_failed", "EMAIL")]
            assert final_pref.is_enabled is True
    finally:
        container.update_user_preference_use_case.reset_override()
        container.get_user_preferences_use_case.reset_override()
        container.unwire()
