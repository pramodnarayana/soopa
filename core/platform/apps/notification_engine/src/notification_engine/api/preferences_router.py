"""
Notification Preferences Router.

Exposes CRUD endpoints for tenant-scoped notification routing rules.
Each rule maps an event_type to one or more delivery channels (EMAIL, SLACK, IN_APP).

Authorization: The authenticated user's authorized tenant IDs are resolved by
AuthenticationMiddleware and stored in request.state.identity. Every endpoint
validates that the requested tenant_id is within the caller's authorized scope.
"""

import logging

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from notification_engine.bootstrap.container import Container
from notification_engine.domain.models import Channel, NotificationPreference
from notification_engine.ports.interfaces import NotificationPreferencesRepositoryPort

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["notification-preferences"],
)

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class NotificationPreferenceResponse(BaseModel):
    """Read DTO for a routing rule — no ORM model leakage across this boundary."""

    id: str
    tenant_id: str
    event_type: str
    channels: list[str]


class UpsertPreferenceRequest(BaseModel):
    """Write DTO for creating / replacing a routing rule."""

    channels: list[str]

    @field_validator("channels")
    @classmethod
    def channels_must_be_valid(cls, v: list[str]) -> list[str]:
        valid = {c.value for c in Channel}
        invalid = set(v) - valid
        if invalid:
            raise ValueError(f"Invalid channel(s): {invalid}. Must be one of {valid}.")
        if not v:
            raise ValueError("At least one channel must be provided.")
        return v


# ---------------------------------------------------------------------------
# Authorization helper
# ---------------------------------------------------------------------------


def _assert_tenant_authorized(request: Request, tenant_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity is not authorized to access
    the requested tenant. Guards all tenant-scoped endpoints against IDOR.
    """
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    authorized: set[str] = getattr(identity, "authorized_tenants", set())
    if tenant_id not in authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this tenant's notification preferences.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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
) -> list[NotificationPreference]:
    _assert_tenant_authorized(request, tenant_id)
    return await repo.list_preferences(tenant_id)


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
) -> NotificationPreference:
    _assert_tenant_authorized(request, tenant_id)
    return await repo.upsert_preference(
        tenant_id=tenant_id,
        event_type=event_type,
        channels=body.channels,
    )


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
    _assert_tenant_authorized(request, tenant_id)
    deleted = await repo.delete_preference(tenant_id=tenant_id, event_type=event_type)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No routing rule found for event_type '{event_type}'",
        )
