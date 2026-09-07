from enum import StrEnum


class NotificationCleanupJobName(StrEnum):
    """
    Canonical event type names for notification cleanup scheduled jobs.
    These must match the event_type values dispatched by the scheduler.
    """

    NOTIFICATION_OUTBOX_CLEANUP = "NOTIFICATION_OUTBOX_CLEANUP"
