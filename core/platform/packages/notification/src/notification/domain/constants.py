from enum import StrEnum


class NotificationEventType(StrEnum):
    """Canonical cross-context event types consumed by the notification worker."""

    NOTIFICATION_TRIGGERED = "notification.triggered"


class NotificationCleanupJobName(StrEnum):
    """
    Canonical event type names for notification cleanup scheduled jobs.
    These must match the event_type values dispatched by the scheduler.
    """

    NOTIFICATION_OUTBOX_CLEANUP = "NOTIFICATION_OUTBOX_CLEANUP"
    NOTIFICATION_OUTBOX_SWEEPER = "NOTIFICATION_OUTBOX_SWEEPER"


class NotificationIdPrefix(StrEnum):
    """Domain-specific ID prefixes for the Notification bounded context."""

    NOTIFICATION_TEMPLATE = "notif_tmpl"
    NOTIFICATION_OUTBOX = "notif_ob"
    NOTIFICATION_ROUTE = "notif_rt"
    NOTIFICATION_RECORD = "notif_rec"
    NOTIFICATION_PREFERENCE = "notif_pref"


class NotificationOutboxSource(StrEnum):
    """Canonical outbox source identifier for Notification events."""

    NOTIFICATION = "notification"


class NotificationOutboxChannel(StrEnum):
    """Canonical PostgreSQL LISTEN/NOTIFY channel names for Notification real-time relays."""

    DELIVERY_WAKEUP = "notification_delivery_outbox_wakeup"
    IN_APP_NOTIFICATIONS = "in_app_notifications"


__all__ = [
    "NotificationCleanupJobName",
    "NotificationEventType",
    "NotificationIdPrefix",
    "NotificationOutboxChannel",
    "NotificationOutboxSource",
]
