from enum import StrEnum


class NotificationIdPrefix(StrEnum):
    TEMPLATE = "notif_tmpl"
    OUTBOX = "notif_ob"
    ROUTE = "notif_rt"
    RECORD = "notif_rec"
    PREFERENCE = "notif_pref"


class NotificationEventType(StrEnum):
    """Canonical cross-context event types consumed by the notification worker."""

    NOTIFICATION_TRIGGERED = "notification.triggered"
