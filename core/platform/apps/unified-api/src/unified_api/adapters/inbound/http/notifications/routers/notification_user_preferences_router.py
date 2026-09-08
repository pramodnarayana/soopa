"""User-scoped notification preference endpoints."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status
from notification.application.get_user_preferences_use_case import GetUserPreferencesUseCase
from notification.application.update_user_preference_use_case import UpdateUserPreferenceUseCase
from notification.bootstrap.container import Container
from notification.domain.models import Channel
from pydantic import BaseModel

from unified_api.adapters.inbound.http.guards.notification_auth_guard import (
    assert_tenant_authorized,
    assert_user_matches_identity,
)

router = APIRouter(prefix="/api/v1/users", tags=["user-notification-preferences"])


class UserNotificationPreferenceResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    event_type: str
    channel: str
    is_enabled: bool


class UpdateUserPreferenceRequest(BaseModel):
    is_enabled: bool


@router.get(
    "/{tenant_id}/{user_id}/notification-preferences",
    response_model=list[UserNotificationPreferenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List all notification preferences for a user",
)
@inject
async def get_user_preferences(
    tenant_id: str,
    user_id: str,
    request: Request,
    use_case: GetUserPreferencesUseCase = Depends(Provide[Container.get_user_preferences_use_case]),
) -> list[UserNotificationPreferenceResponse]:
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)
    preferences = await use_case.execute(tenant_id, user_id)
    return [
        UserNotificationPreferenceResponse(
            id=preference.id,
            tenant_id=preference.tenant_id,
            user_id=preference.user_id,
            event_type=preference.event_type,
            channel=preference.channel,
            is_enabled=preference.is_enabled,
        )
        for preference in preferences
    ]


@router.patch(
    "/{tenant_id}/{user_id}/notification-preferences/{event_type}/{channel}",
    response_model=UserNotificationPreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a notification preference for a specific event type and channel",
)
@inject
async def update_user_preference(
    tenant_id: str,
    user_id: str,
    event_type: str,
    channel: Channel,
    body: UpdateUserPreferenceRequest,
    request: Request,
    use_case: UpdateUserPreferenceUseCase = Depends(
        Provide[Container.update_user_preference_use_case]
    ),
) -> UserNotificationPreferenceResponse:
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)

    preference = await use_case.execute(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=channel,
        is_enabled=body.is_enabled,
    )
    return UserNotificationPreferenceResponse(
        id=preference.id,
        tenant_id=preference.tenant_id,
        user_id=preference.user_id,
        event_type=preference.event_type,
        channel=preference.channel,
        is_enabled=preference.is_enabled,
    )
