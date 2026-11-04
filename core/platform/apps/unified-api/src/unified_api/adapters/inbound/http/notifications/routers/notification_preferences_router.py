"""Tenant-scoped notification routing rule endpoints."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from notification.bootstrap.container import Container
from notification.domain.enums import Channel
from notification.domain.preference import NotificationPreference
from notification.ports.outbound.notification_preferences_repository_port import (
    NotificationPreferencesRepositoryPort,
)
from pydantic import BaseModel, field_validator

from unified_api.adapters.inbound.http.guards.notification_auth_guard import (
    assert_tenant_authorized,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notification-preferences"])


class NotificationPreferenceResponse(BaseModel):
    """Read DTO for a routing rule."""

    id: str
    tenant_id: str
    event_type: str
    channels: list[str]


class UpsertPreferenceRequest(BaseModel):
    """Write DTO for creating or replacing a routing rule."""

    channels: list[str]

    @field_validator("channels")
    @classmethod
    def channels_must_be_valid(cls, value: list[str]) -> list[str]:
        valid = {channel.value for channel in Channel}
        invalid = set(value) - valid
        if invalid:
            raise ValueError(f"Invalid channel(s): {invalid}. Must be one of {valid}.")
        if not value:
            raise ValueError("At least one channel must be provided.")
        return value


def _to_preference_response(
    preference: NotificationPreference,
) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        id=preference.id,
        tenant_id=preference.tenant_id,
        event_type=preference.event_type,
        channels=[ch.value for ch in preference.channels],
    )


@router.get(
    "/{tenant_id}/preferences",
    response_model=list[NotificationPreferenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List all notification routing rules for a tenant",
)
@inject
async def list_preferences(
    tenant_id: str,
    request: Request,
    repo: NotificationPreferencesRepositoryPort = Depends(Provide[Container.route_repository]),
) -> list[NotificationPreferenceResponse]:
    assert_tenant_authorized(request, tenant_id)
    preferences = await repo.list_preferences(tenant_id)
    return [_to_preference_response(p) for p in preferences]


@router.put(
    "/{tenant_id}/preferences/{event_type}",
    response_model=NotificationPreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert a notification routing rule for a specific event type",
)
@inject
async def upsert_preference(
    tenant_id: str,
    event_type: str,
    body: UpsertPreferenceRequest,
    request: Request,
    repo: NotificationPreferencesRepositoryPort = Depends(Provide[Container.route_repository]),
) -> NotificationPreferenceResponse:
    assert_tenant_authorized(request, tenant_id)
    preference = await repo.upsert_preference(
        tenant_id=tenant_id,
        event_type=event_type,
        channels=body.channels,
    )
    return _to_preference_response(preference)


@router.delete(
    "/{tenant_id}/preferences/{event_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification routing rule for a specific event type",
)
@inject
async def delete_preference(
    tenant_id: str,
    event_type: str,
    request: Request,
    repo: NotificationPreferencesRepositoryPort = Depends(Provide[Container.route_repository]),
) -> None:
    assert_tenant_authorized(request, tenant_id)
    deleted = await repo.delete_preference(tenant_id=tenant_id, event_type=event_type)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No routing rule found for event_type '{event_type}'",
        )
