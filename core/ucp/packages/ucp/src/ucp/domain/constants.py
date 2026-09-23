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
    UCP_OUTBOX_CLEANUP = "UCP_OUTBOX_CLEANUP"
    UCP_IDEMPOTENCY_CLEANUP = "UCP_IDEMPOTENCY_CLEANUP"
    UCP_AUDIT_LOG_CLEANUP = "UCP_AUDIT_LOG_CLEANUP"
