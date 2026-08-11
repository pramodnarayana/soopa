from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NotificationDTO:
    id: str
    title: str
    body: str
    is_read: bool
    created_at: str | None


class NotificationQueryPort(Protocol):
    """
    Port for querying user notifications, separating the UI Presentation layer
    from the concrete Database adapters.
    """

    async def get_in_app_notifications(
        self, tenant_id: str, user_id: str, limit: int = 50
    ) -> list[NotificationDTO]: ...

    async def mark_as_read(self, tenant_id: str, user_id: str, notification_id: str) -> bool: ...
