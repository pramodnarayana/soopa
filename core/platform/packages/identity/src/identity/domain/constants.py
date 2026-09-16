from enum import StrEnum


class IdentityEventType(StrEnum):
    TENANT_PROVISIONED = "tenant.provisioned"
    APP_SUBSCRIBED = "app.subscribed"
    APP_UNSUBSCRIBED = "app.unsubscribed"
    USER_INVITED = "UserInvited"
    USER_UPDATED = "UserUpdated"
    USER_ROLE_ASSIGNED = "user_role_assigned"
    USER_STATUS_TOGGLED = "UserStatusToggled"
    USER_DELETED = "UserDeleted"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class IdentityJobName(StrEnum):
    """
    Canonical job type names dispatched by the scheduler to identity workers.
    These must match the event_type values sent by the scheduler.
    """

    IDENTITY_OUTBOX_SWEEPER = "IDENTITY_OUTBOX_SWEEPER"
    IDENTITY_OUTBOX_CLEANUP = "IDENTITY_OUTBOX_CLEANUP"
