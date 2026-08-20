from typing import Any, Protocol


class InAppNotificationPersistencePort(Protocol):
    async def save_notification(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...
