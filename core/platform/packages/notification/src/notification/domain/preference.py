from dataclasses import dataclass

from notification.domain.enums import Channel


@dataclass(frozen=True)
class NotificationPreference:
    id: str
    tenant_id: str
    event_type: str
    channels: tuple[Channel, ...]


@dataclass(frozen=True)
class UserNotificationPreference:
    id: str
    tenant_id: str
    user_id: str
    event_type: str
    channel: Channel
    is_enabled: bool


__all__ = [
    "NotificationPreference",
    "UserNotificationPreference",
]
