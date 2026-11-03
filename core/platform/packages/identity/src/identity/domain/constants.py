from enum import StrEnum


class IdentityEventType(StrEnum):
    TENANT_PROVISIONED = "tenant.provisioned"
    TENANT_NAME_UPDATED = "tenant.name_updated"
    TENANT_STATUS_TOGGLED = "tenant.status_toggled"
    TENANT_DELETED = "tenant.deleted"
    APP_SUBSCRIBED = "app.subscribed"
    APP_UNSUBSCRIBED = "app.unsubscribed"
    USER_INVITED = "user.invited"
    USER_UPDATED = "user.updated"
    USER_ROLE_ASSIGNED = "user.role_assigned"
    USER_STATUS_TOGGLED = "user.status_toggled"
    USER_DELETED = "user.deleted"
    USER_MEMBERSHIP_REMOVED = "user.membership_removed"
    ROLE_CREATED = "role.created"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class UserStatusAction(StrEnum):
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class IdentityJobName(StrEnum):
    """
    Canonical job type names dispatched by the scheduler to identity workers.
    These must match the event_type values sent by the scheduler.
    """

    IDENTITY_OUTBOX_SWEEPER = "IDENTITY_OUTBOX_SWEEPER"
    IDENTITY_OUTBOX_CLEANUP = "IDENTITY_OUTBOX_CLEANUP"


class IdentityOutboxSource(StrEnum):
    """Canonical outbox source identifier for Identity events."""

    IDENTITY = "soopa.identity"


class IdentityIdPrefix(StrEnum):
    """Domain-specific ID prefixes for the Identity bounded context."""

    TENANT = "iam_ten"
    USER = "iam_usr"
    TOKEN = "iam_tok"  # noqa: S105 - Entity ID prefix for IAM API tokens, not a secret credential
    KEY = "iam_key"
    ROLE = "iam_rol"
    USER_ROLE = "iam_usr_rol"
    IDENTITY_OUTBOX = "iam_ob"


__all__ = [
    "IdentityEventType",
    "IdentityIdPrefix",
    "IdentityJobName",
    "IdentityOutboxSource",
    "UserStatus",
    "UserStatusAction",
]
