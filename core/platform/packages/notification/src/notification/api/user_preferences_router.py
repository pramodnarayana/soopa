"""
User Notification Preferences Router.

Exposes CRUD endpoints for user-scoped notification preferences.
Each rule maps an event_type + channel to a boolean (is_enabled).
"""

import structlog
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from notification.api.authorization import assert_tenant_authorized, assert_user_matches_identity
from notification.application.get_user_preferences_use_case import GetUserPreferencesUseCase
from notification.application.update_user_preference_use_case import UpdateUserPreferenceUseCase
from notification.bootstrap.container import Container
from notification.domain.models import Channel

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/users",
    tags=["user-notification-preferences"],
)

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class UserNotificationPreferenceResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    event_type: str
    channel: str
    is_enabled: bool


class UpdateUserPreferenceRequest(BaseModel):
    is_enabled: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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
    use_case: GetUserPreferencesUseCase = Depends(  # noqa: B008
        Provide[Container.get_user_preferences_use_case]
    ),
) -> list[UserNotificationPreferenceResponse]:
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)
    prefs = await use_case.execute(tenant_id, user_id)
    return [
        UserNotificationPreferenceResponse(
            id=p.id,
            tenant_id=p.tenant_id,
            user_id=p.user_id,
            event_type=p.event_type,
            channel=p.channel,
            is_enabled=p.is_enabled,
        )
        for p in prefs
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
    use_case: UpdateUserPreferenceUseCase = Depends(  # noqa: B008
        Provide[Container.update_user_preference_use_case]
    ),
) -> UserNotificationPreferenceResponse:
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)

    pref = await use_case.execute(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=channel,
        is_enabled=body.is_enabled,
    )
    return UserNotificationPreferenceResponse(
        id=pref.id,
        tenant_id=pref.tenant_id,
        user_id=pref.user_id,
        event_type=pref.event_type,
        channel=pref.channel,
        is_enabled=pref.is_enabled,
    )
