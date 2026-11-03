from enum import StrEnum

from seedwork.constants import LifecycleStatus as LifecycleStatus


class UcpEventType(StrEnum):
    APP_SUBSCRIBED = "app.subscribed"
    APP_UNSUBSCRIBED = "app.unsubscribed"
    ROLE_CREATED = "role.created"
    USER_ROLE_ASSIGNED = "user.role_assigned"
    TENANT_PROVISIONED = "tenant.provisioned"
    TENANT_NAME_UPDATED = "tenant.name_updated"
    TENANT_STATUS_TOGGLED = "tenant.status_toggled"
    TENANT_DELETED = "tenant.deleted"
    USER_UPDATED = "user.updated"
    USER_STATUS_TOGGLED = "user.status_toggled"
    USER_DELETED = "user.deleted"
    USER_MEMBERSHIP_REMOVED = "user.membership_removed"


class SubscriptionTier(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class UcpJobName(StrEnum):
    UCP_OUTBOX_SWEEPER = "UCP_OUTBOX_SWEEPER"


class UcpCleanupJobName(StrEnum):
    """
    Canonical event type names for UCP cleanup scheduled jobs.
    These must match the event_type values dispatched by the scheduler.
    """

    UCP_OUTBOX_CLEANUP = "UCP_OUTBOX_CLEANUP"
    UCP_IDEMPOTENCY_CLEANUP = "UCP_IDEMPOTENCY_CLEANUP"
    UCP_AUDIT_LOG_CLEANUP = "UCP_AUDIT_LOG_CLEANUP"


class UcpIdPrefix(StrEnum):
    """Domain-specific ID prefixes for the UCP bounded context."""

    TENANT = "iam_ten"
    USER = "iam_usr"
    TOKEN = "iam_tok"  # noqa: S105 - Entity ID prefix for IAM API tokens, not a secret credential
    KEY = "iam_key"
    ROLE = "iam_rol"
    USER_ROLE = "iam_usr_rol"
    APP = "ucp_app"
    UCP_APP = "ucp_app"
    SHARD = "ucp_shard"
    UCP_SHARD = "ucp_shard"
    OUTBOX = "ucp_ob"
    UCP_OUTBOX = "ucp_ob"
    WEBHOOK = "ucp_wh"
    UCP_WEBHOOK = "ucp_wh"


class UcpOutboxSource(StrEnum):
    """Canonical outbox source identifier for UCP events."""

    UCP = "soopa.ucp"


__all__ = [
    "IdempotencyStatus",
    "LifecycleStatus",
    "SubscriptionTier",
    "UcpCleanupJobName",
    "UcpEventType",
    "UcpIdPrefix",
    "UcpJobName",
    "UcpOutboxSource",
]
