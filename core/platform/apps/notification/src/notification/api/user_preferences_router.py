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
from notification.application.update_user_preference_use_case import UpdateUserPreferenceUseCase
from notification.bootstrap.container import Container
from notification.domain.models import Channel, UserNotificationPreference
from notification.ports.interfaces import UserNotificationPreferenceRepositoryPort

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
    repo: UserNotificationPreferenceRepositoryPort = Depends(  # noqa: B008
        Provide[Container.user_preference_repository]
    ),
) -> list[UserNotificationPreference]:
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)
    return await repo.get_user_preferences(tenant_id, user_id)


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
) -> UserNotificationPreference:
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)

    return await use_case.execute(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=channel,
        is_enabled=body.is_enabled,
    )
