from enum import StrEnum

from seedwork.constants import LifecycleStatus as LifecycleStatus


class UcpIdPrefix(StrEnum):
    APP = "ucp_app"
    SHARD = "ucp_shard"
    OUTBOX = "ucp_ob"
    WEBHOOK = "ucp_wh"


class UcpEventType(StrEnum):
    APP_SUBSCRIBED = "app.subscribed"
    APP_UNSUBSCRIBED = "app.unsubscribed"
    ROLE_CREATED = "role_created"
    USER_ROLE_ASSIGNED = "user_role_assigned"
    TENANT_PROVISIONED = "tenant.provisioned"
    TENANT_NAME_UPDATED = "TenantNameUpdated"
    TENANT_STATUS_TOGGLED = "TenantStatusToggled"
    TENANT_DELETED = "TenantDeleted"
    USER_UPDATED = "UserUpdated"
    USER_STATUS_TOGGLED = "UserStatusToggled"
    USER_DELETED = "UserDeleted"
    USER_MEMBERSHIP_REMOVED = "UserMembershipRemoved"


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
