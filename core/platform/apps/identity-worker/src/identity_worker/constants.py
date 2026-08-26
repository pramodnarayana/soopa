from enum import StrEnum


class IdentityJobName(StrEnum):
    """
    Canonical event type names for identity worker scheduled jobs.
    These must match the event_type values dispatched by the scheduler.
    """

    IDENTITY_OUTBOX_SWEEPER = "IDENTITY_OUTBOX_SWEEPER"
    IDENTITY_OUTBOX_CLEANUP = "IDENTITY_OUTBOX_CLEANUP"
