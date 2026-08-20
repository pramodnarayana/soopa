# We use the FastAPI Request to extract the container for dependency injection
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from notification.api.authorization import (
    assert_tenant_authorized,
    assert_user_matches_identity,
)
from notification.application.ports.notification_query_port import (
    NotificationDTO,
    NotificationQueryPort,
)
from notification.bootstrap.container import Container

router = APIRouter(prefix="/api/v1/notifications", tags=["in-app-notifications"])


@router.get("/{tenant_id}/users/{user_id}/in-app", status_code=status.HTTP_200_OK)
@inject
async def get_user_notifications(
    tenant_id: str,
    user_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    repo: NotificationQueryPort = Depends(Provide[Container.query_repository]),  # noqa: B008
) -> list[NotificationDTO]:
    """
    Fetches the latest In-App notifications for a specific user in a tenant.
    """
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)
    return await repo.get_in_app_notifications(tenant_id, user_id, limit)


@router.put(
    "/{tenant_id}/users/{user_id}/in-app/{notification_id}/read", status_code=status.HTTP_200_OK
)
@inject
async def mark_notification_read(
    tenant_id: str,
    user_id: str,
    notification_id: str,
    request: Request,
    repo: NotificationQueryPort = Depends(Provide[Container.query_repository]),  # noqa: B008
) -> dict[str, str]:
    """
    Marks a specific notification as read.
    """
    assert_tenant_authorized(request, tenant_id)
    assert_user_matches_identity(request, user_id)
    success = await repo.mark_as_read(tenant_id, user_id, notification_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found or already read"
        )
    return {"status": "success"}
