from unittest.mock import AsyncMock

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

    from notification.api.user_preferences_router import router
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

    # Mock Use Case
    mock_use_case = AsyncMock(spec=UpdateUserPreferenceUseCase)
    mock_use_case.execute.return_value = UserNotificationPreference(
        id="notif_pref_123",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type="invoice.payment_failed",
        channel=Channel.EMAIL,
        is_enabled=True,
    )

    # Mock Repo for GET
    mock_repo = AsyncMock()
    mock_repo.get_user_preferences.return_value = [
        UserNotificationPreference(
            id="notif_pref_123",
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="invoice.payment_failed",
            channel=Channel.EMAIL,
            is_enabled=False,
        )
    ]

    container.update_user_preference_use_case.override(providers.Object(mock_use_case))
    container.user_preference_repository.override(providers.Object(mock_repo))
    container.wire(modules=["notification.api.user_preferences_router"])

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
            mock_use_case.execute.assert_called_once_with(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type="invoice.payment_failed",
                channel="EMAIL",
                is_enabled=True,
            )

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
            # Verify repository was not called for unauthorized access
            mock_repo.get_user_preferences.assert_called_once()  # Only from step 1

            # 5. PATCH with different user in x-mock-user header (IDOR test - same tenant)
            response = await ac.patch(
                f"/api/v1/users/{tenant_id}/{user_id}/notification-preferences/invoice.payment_failed/EMAIL",
                json={"is_enabled": True},
                headers={"x-mock-user": different_user},
            )
            assert response.status_code == 403
            # Verify use case was not called for unauthorized access
            mock_use_case.execute.assert_called_once()  # Only from step 2
    finally:
        container.update_user_preference_use_case.reset_override()
        container.user_preference_repository.reset_override()
        container.unwire()
