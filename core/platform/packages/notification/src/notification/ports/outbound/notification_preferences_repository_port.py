from typing import Protocol

from notification.domain.models import NotificationPreference


class NotificationPreferencesRepositoryPort(Protocol):
    """Port for reading and writing tenant notification routing rules."""

    async def list_preferences(self, tenant_id: str) -> list[NotificationPreference]: ...

    async def upsert_preference(
        self,
        tenant_id: str,
        event_type: str,
        channels: list[str],
    ) -> NotificationPreference: ...

    async def delete_preference(self, tenant_id: str, event_type: str) -> bool: ...
