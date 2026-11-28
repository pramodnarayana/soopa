from enum import StrEnum

IDENTITY_CONFIG_APP_ID = "identity"
MAX_IMPERSONATION_TTL_SECONDS = 3600
TOKEN_REVOCATION_CLOCK_SKEW_SECONDS = 1
MFA_AMR_VALUES: frozenset[str] = frozenset({"mfa", "otp", "totp", "hwk", "webauthn", "fido", "sms"})


class IdentityEventType(StrEnum):
    TENANT_PROVISIONED = "tenant.provisioned"
    TENANT_NAME_UPDATED = "tenant.name_updated"
    TENANT_STATUS_TOGGLED = "tenant.status_toggled"
    TENANT_DELETED = "tenant.deleted"
    TENANT_TOKENS_REVOKED = "tenant.tokens_revoked"
    APP_SUBSCRIBED = "app.subscribed"
    APP_UNSUBSCRIBED = "app.unsubscribed"
    USER_INVITED = "user.invited"
    USER_UPDATED = "user.updated"
    USER_ROLE_ASSIGNED = "user.role_assigned"
    USER_STATUS_TOGGLED = "user.status_toggled"
    USER_DELETED = "user.deleted"
    USER_MEMBERSHIP_REMOVED = "user.membership_removed"
    USER_TOKENS_REVOKED = "user.tokens_revoked"
    ROLE_CREATED = "role.created"
    RESOURCE_GRANT_UPDATED = "resource_grant.updated"
    POLICY_RULE_UPDATED = "policy_rule.updated"
    EXTERNAL_IDENTITY_LINKED = "external_identity.linked"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class UserStatusAction(StrEnum):
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class TenantTierType(StrEnum):
    """Canonical multi-tier tenancy classification across B2C, SMB, and Enterprise SaaS."""

    PLATFORM = "PLATFORM"
    PERSONAL = "PERSONAL"
    CONSUMER_POOL = "CONSUMER_POOL"
    PARTNER = "PARTNER"
    ORGANIZATION = "ORGANIZATION"
    WORKSPACE = "WORKSPACE"


class TenantIsolationMode(StrEnum):
    """Authentication realm isolation policy for a tenant."""

    POOLED_REALM = "POOLED_REALM"
    DEDICATED_IDP_ORG = "DEDICATED_IDP_ORG"


class MembershipScope(StrEnum):
    """Controls whether a membership applies strictly to one node or inherits to descendants."""

    DIRECT = "DIRECT"
    SUBTREE = "SUBTREE"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    MACHINE = "MACHINE"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    DELEGATED_SUPPORT = "DELEGATED_SUPPORT"


class AuthzEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class AuthzReasonCode(StrEnum):
    ALLOWED_BY_CAPABILITY = "ALLOWED_BY_CAPABILITY"
    ALLOWED_BY_RESOURCE_GRANT = "ALLOWED_BY_RESOURCE_GRANT"
    ALLOWED_BY_ABAC_OWNERSHIP = "ALLOWED_BY_ABAC_OWNERSHIP"
    ALLOWED_BY_CASBIN_POLICY = "ALLOWED_BY_CASBIN_POLICY"
    DENIED_UNAUTHENTICATED = "DENIED_UNAUTHENTICATED"
    DENIED_UNTRUSTED_ISSUER = "DENIED_UNTRUSTED_ISSUER"
    DENIED_TOKEN_REVOKED = "DENIED_TOKEN_REVOKED"  # noqa: S105 - AuthZ reason code enum constant, not a secret credential
    DENIED_SSO_REQUIRED = "DENIED_SSO_REQUIRED"
    DENIED_ACCOUNT_SUSPENDED = "DENIED_ACCOUNT_SUSPENDED"
    DENIED_TENANT_SUSPENDED = "DENIED_TENANT_SUSPENDED"
    DENIED_TENANT_NOT_FOUND = "DENIED_TENANT_NOT_FOUND"
    DENIED_TENANT_SCOPE_MISMATCH = "DENIED_TENANT_SCOPE_MISMATCH"
    DENIED_APP_NOT_SUBSCRIBED = "DENIED_APP_NOT_SUBSCRIBED"
    DENIED_NOT_TENANT_MEMBER = "DENIED_NOT_TENANT_MEMBER"
    DENIED_EXPLICIT_POLICY = "DENIED_EXPLICIT_POLICY"
    DENIED_MACHINE_ACTION_FORBIDDEN = "DENIED_MACHINE_ACTION_FORBIDDEN"
    DENIED_STEP_UP_MFA_REQUIRED = "DENIED_STEP_UP_MFA_REQUIRED"
    DENIED_IMPERSONATION_POLICY = "DENIED_IMPERSONATION_POLICY"
    DENIED_MISSING_CAPABILITY = "DENIED_MISSING_CAPABILITY"
    DENIED_RESOURCE_ACCESS = "DENIED_RESOURCE_ACCESS"


class AuthzObligation(StrEnum):
    REQUIRE_MFA_STEP_UP = "REQUIRE_MFA_STEP_UP"
    REDIRECT_ENTERPRISE_SSO = "REDIRECT_ENTERPRISE_SSO"


class ResourceSubjectType(StrEnum):
    USER = "USER"
    ROLE = "ROLE"
    GROUP = "GROUP"
    TENANT = "TENANT"


class ResourceClassification(StrEnum):
    PUBLIC = "PUBLIC"
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"


class PolicyEngineType(StrEnum):
    CASBIN = "CASBIN"
    ABAC = "ABAC"


class IdentityConfigEntityType(StrEnum):
    """Low-cardinality catalog entities & invalidation tombstones streamed via config-sync."""

    TRUSTED_ISSUER = "TRUSTED_ISSUER"
    CAPABILITY = "CAPABILITY"
    PLATFORM_ROLE = "PLATFORM_ROLE"
    EMAIL_DOMAIN_ROUTE = "EMAIL_DOMAIN_ROUTE"
    POLICY_RULE = "POLICY_RULE"
    USER_REVOCATION = "USER_REVOCATION"
    TENANT_UPDATED = "TENANT_UPDATED"
    SUBSCRIPTION_UPDATED = "SUBSCRIPTION_UPDATED"
    ROLE_UPDATED = "ROLE_UPDATED"


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


class CoreControlPlaneAppSlug(StrEnum):
    """Canonical core control-plane application slugs (domain-agnostic; zero business app leakage)."""

    PLATFORM = "platform"
    UCP = "ucp"
    IDENTITY = "identity"


class IdentityIdPrefix(StrEnum):
    """Domain-specific ID prefixes for the Identity bounded context."""

    TENANT = "iam_ten"
    USER = "iam_usr"
    TOKEN = "iam_tok"  # noqa: S105 - Entity ID prefix for IAM API tokens, not a secret credential
    KEY = "iam_key"
    ROLE = "iam_rol"
    USER_ROLE = "iam_usr_rol"
    IDENTITY_OUTBOX = "iam_ob"
    EXTERNAL_IDENTITY = "iam_ext"
    RESOURCE_GRANT = "iam_grt"
    POLICY_RULE = "iam_pol"


CANONICAL_TENANT_ID_PREFIXES: tuple[str, ...] = ("ten_", f"{IdentityIdPrefix.TENANT.value}_")


__all__ = [
    "CANONICAL_TENANT_ID_PREFIXES",
    "IDENTITY_CONFIG_APP_ID",
    "MAX_IMPERSONATION_TTL_SECONDS",
    "MFA_AMR_VALUES",
    "TOKEN_REVOCATION_CLOCK_SKEW_SECONDS",
    "ActorType",
    "AuthzEffect",
    "AuthzObligation",
    "AuthzReasonCode",
    "CoreControlPlaneAppSlug",
    "IdentityConfigEntityType",
    "IdentityEventType",
    "IdentityIdPrefix",
    "IdentityJobName",
    "IdentityOutboxSource",
    "MembershipScope",
    "MembershipStatus",
    "PolicyEngineType",
    "ResourceClassification",
    "ResourceSubjectType",
    "TenantIsolationMode",
    "TenantTierType",
    "UserStatus",
    "UserStatusAction",
]
