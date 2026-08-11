import asyncio
import json
from collections.abc import AsyncGenerator

# We use the FastAPI Request to extract the container for dependency injection
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from notification_engine.api.authorization import (
    _assert_tenant_authorized,
    _assert_user_matches_identity,
)
from notification_engine.application.ports.notification_query_port import (
    NotificationDTO,
    NotificationQueryPort,
)
from notification_engine.application.ports.notification_stream_port import NotificationStreamPort
from notification_engine.bootstrap.container import Container

router = APIRouter(prefix="/api/v1/notifications", tags=["in-app-notifications"])


@router.get("/{tenant_id}/users/{user_id}/in-app", status_code=status.HTTP_200_OK)
@inject
async def get_user_notifications(
    tenant_id: str,
    user_id: str,
    request: Request,
    limit: int = 50,
    repo: NotificationQueryPort = Depends(Provide[Container.query_repository]),  # noqa: B008
) -> list[NotificationDTO]:
    """
    Fetches the latest In-App notifications for a specific user in a tenant.
    """
    _assert_tenant_authorized(request, tenant_id)
    _assert_user_matches_identity(request, user_id)
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
    _assert_tenant_authorized(request, tenant_id)
    _assert_user_matches_identity(request, user_id)
    success = await repo.mark_as_read(tenant_id, user_id, notification_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found or already read"
        )
    return {"status": "success"}


@router.get("/{tenant_id}/users/{user_id}/stream")
@inject
async def stream_notifications(
    tenant_id: str,
    user_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    stream_manager: NotificationStreamPort = Depends(Provide[Container.stream_manager]),  # noqa: B008
) -> StreamingResponse:
    """
    Server-Sent Events (SSE) endpoint to stream new notifications to the UI in real-time.
    """
    _assert_tenant_authorized(request, tenant_id)
    _assert_user_matches_identity(request, user_id)

    queue = stream_manager.subscribe(tenant_id, user_id)

    async def event_generator() -> AsyncGenerator[str]:
        try:
            heartbeat_interval = 30  # seconds
            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                # Check if we should send a heartbeat
                current_time = asyncio.get_event_loop().time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    yield ": heartbeat\n\n"
                    last_heartbeat = current_time

                try:
                    # Wait for a new notification with a timeout to allow heartbeat checks
                    notification = await asyncio.wait_for(queue.get(), timeout=5.0)

                    # Format as Server-Sent Event
                    data = json.dumps(
                        {
                            "id": notification.id,
                            "title": notification.title,
                            "body": notification.body,
                            "severity": notification.severity,
                            "is_read": notification.is_read,
                            "created_at": notification.created_at,
                        }
                    )

                    yield f"data: {data}\n\n"
                except TimeoutError:
                    # No notification received, continue loop to send heartbeat if needed
                    continue
        finally:
            # Always unsubscribe on any exit path (cancellation, error, etc.)
            stream_manager.unsubscribe(tenant_id, user_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
