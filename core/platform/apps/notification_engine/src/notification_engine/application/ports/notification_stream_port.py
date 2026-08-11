import asyncio
from typing import Protocol

from notification_engine.application.ports.notification_query_port import NotificationDTO


class NotificationStreamPort(Protocol):
    """
    Port for managing SSE streams and broadcasting notifications.
    This separates the FastAPI streaming endpoints from the concrete
    queue manager implementation.
    """

    def subscribe(self, tenant_id: str, user_id: str) -> asyncio.Queue[NotificationDTO]: ...

    def unsubscribe(
        self, tenant_id: str, user_id: str, queue: asyncio.Queue[NotificationDTO]
    ) -> None: ...

    async def broadcast(
        self, tenant_id: str, user_id: str, notification: NotificationDTO
    ) -> None: ...
