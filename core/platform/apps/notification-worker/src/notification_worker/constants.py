from enum import StrEnum


class NotificationJobName(StrEnum):
    """
    Canonical event type names for notification worker scheduled jobs.
    These must match the event_type values dispatched by the scheduler.
    """

    NOTIFICATION_OUTBOX_SWEEPER = "NOTIFICATION_OUTBOX_SWEEPER"
