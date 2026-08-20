from typing import Protocol

from notification.domain.models import UserNotificationPreference


class UserNotificationPreferenceRepositoryPort(Protocol):
    """Port for fetching and updating user notification preferences."""

    async def get_preference(
        self, tenant_id: str, user_id: str, event_type: str, channel: str
    ) -> UserNotificationPreference | None: ...

    async def get_user_preferences(
        self, tenant_id: str, user_id: str
    ) -> list[UserNotificationPreference]: ...

    async def save_preference(self, preference: UserNotificationPreference) -> None: ...
