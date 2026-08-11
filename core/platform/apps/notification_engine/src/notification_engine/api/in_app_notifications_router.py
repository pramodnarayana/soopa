import asyncio
import json
from collections.abc import AsyncGenerator

# We use the FastAPI Request to extract the container for dependency injection
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

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
    limit: int = 50,
    repo: NotificationQueryPort = Depends(Provide[Container.query_repository]),
) -> list[NotificationDTO]:
    """
    Fetches the latest In-App notifications for a specific user in a tenant.
    """
    return await repo.get_in_app_notifications(tenant_id, user_id, limit)


@router.put(
    "/{tenant_id}/users/{user_id}/in-app/{notification_id}/read", status_code=status.HTTP_200_OK
)
@inject
async def mark_notification_read(
    tenant_id: str,
    user_id: str,
    notification_id: str,
    repo: NotificationQueryPort = Depends(Provide[Container.query_repository]),
) -> dict[str, str]:
    """
    Marks a specific notification as read.
    """
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
    stream_manager: NotificationStreamPort = Depends(Provide[Container.stream_manager]),
) -> StreamingResponse:
    """
    Server-Sent Events (SSE) endpoint to stream new notifications to the UI in real-time.
    """
    queue = stream_manager.subscribe(tenant_id, user_id)

    async def event_generator() -> AsyncGenerator[str]:
        try:
            while True:
                # Wait for a new notification
                notification = await queue.get()

                # Format as Server-Sent Event
                data = json.dumps(
                    {
                        "id": notification.id,
                        "title": notification.title,
                        "body": notification.body,
                        "is_read": notification.is_read,
                        "created_at": notification.created_at,
                    }
                )

                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            stream_manager.unsubscribe(tenant_id, user_id, queue)
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")
