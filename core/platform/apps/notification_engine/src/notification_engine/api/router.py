import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..application.dispatch_use_case import DispatchNotificationUseCase
from ..domain.models import Channel, NotificationEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationEventPayload(BaseModel):
    tenantId: str
    eventType: str
    channels: list[Channel]
    data: dict[str, Any]


def get_dispatch_use_case() -> DispatchNotificationUseCase:
    from ..main import container

    return container.resolve(DispatchNotificationUseCase)


@router.post("/send", status_code=status.HTTP_202_ACCEPTED)
async def send_notification(
    payload: NotificationEventPayload,
    use_case: DispatchNotificationUseCase = Depends(get_dispatch_use_case)
) -> dict[str, str]:
    try:
        logger.info(f"Received notification dispatch request for eventType: {payload.eventType}")
        event = NotificationEvent(
            tenant_id=payload.tenantId,
            event_type=payload.eventType,
            channels=payload.channels,
            data=payload.data,
        )
        await use_case.execute(event)
        return {"status": "ACCEPTED"}
    except Exception as e:
        logger.error(f"Failed to dispatch notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
