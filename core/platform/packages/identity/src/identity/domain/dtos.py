"""Strictly typed, immutable Domain & Boundary DTOs for IdP-Agnostic Identity & Authorization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from seedwork.domain.types import JsonDict, JsonPrimitive

from identity.domain.constants import (
    ActorType,
    AuthzEffect,
    AuthzObligation,
    AuthzReasonCode,
    MembershipScope,
    MembershipStatus,
    PolicyEngineType,
    ResourceClassification,
    ResourceSubjectType,
    TenantIsolationMode,
    TenantTierType,
    UserStatus,
)


@dataclass(frozen=True, kw_only=True)
class PrincipalContext:
    """Strictly immutable authenticated principal (NEVER mutated in-place)."""

    user_id: str
    idp_issuer: str
    idp_subject: str
    actor_type: ActorType
    token_issued_at: datetime
    assurance_level: str = "aal1"
    mfa_verified: bool = False
    email: str | None = None
    email_verified: bool = False
    idp_realm: str | None = None
    bound_tenant_id: str | None = None
    token_scopes: frozenset[str] | None = None
    impersonator_user_id: str | None = None
    impersonation_ticket_id: str | None = None
    impersonation_expires_at: datetime | None = None
    jti: str | None = None


@dataclass(frozen=True, kw_only=True)
class ResourceContext:
    """Typed target resource metadata for ABAC and ReBAC authorization checks."""

    resource_type: str
    resource_id: str | None = None
    tenant_id: str | None = None
    owner_user_id: str | None = None
    classification: ResourceClassification = ResourceClassification.STANDARD
    attributes: Mapping[str, JsonPrimitive] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class AuthzRequest:
    """Immutable authorization evaluation request."""

    principal: PrincipalContext
    app_slug: str
    action: str
    tenant_id: str
    resource: ResourceContext | None = None
    client_ip: str | None = None
    now: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class AuthzDecision:
    """First-class immutable authorization verdict (no exceptions for expected denials)."""

    effect: AuthzEffect
    reason_code: AuthzReasonCode
    matched_policy_id: str | None = None
    obligations: tuple[AuthzObligation, ...] = ()
    evaluated_in_us: int = 0

    @property
    def is_allowed(self) -> bool:
        return self.effect == AuthzEffect.ALLOW


@dataclass(frozen=True, kw_only=True)
class TrustedIssuerDTO:
    """Registered OIDC token issuer allowed to authenticate requests."""

    issuer: str
    jwks_uri: str
    allowed_audiences: tuple[str, ...] = ()
    jwks_host_header: str | None = None
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class EmailDomainRouteDTO:
    """Home Realm Discovery (HRD) and Enterprise SSO enforcement route for a verified domain."""

    domain: str
    tenant_id: str
    idp_issuer: str
    idp_realm_name: str
    sso_enforced: bool = False
    verified_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class HomeRealmDecisionDTO:
    """Immutable Home Realm Discovery decision (100% IdP-agnostic & anti-enumeration)."""

    realm: str
    issuer: str
    client_id: str
    require_sso: bool = False
    sso_provider: str | None = None
    tenant_id: str | None = None
    login_hint: str | None = None


@dataclass(frozen=True, kw_only=True)
class TenantNodeDTO:
    """Immutable projection of an `identity.tenants` hierarchy node."""

    id: str
    parent_tenant_id: str | None
    hierarchy_path: str
    tier_type: TenantTierType
    isolation_mode: TenantIsolationMode
    status: str
    block_parent_inheritance: bool
    tokens_valid_after: datetime
    idp_realm_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class MembershipDTO:
    """Immutable projection of an `identity.tenant_users` membership row."""

    user_id: str
    tenant_id: str
    scope: MembershipScope = MembershipScope.DIRECT
    status: MembershipStatus = MembershipStatus.ACTIVE
    expires_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class UserRoleAssignmentDTO:
    """Immutable projection of an `identity.user_roles` binding."""

    tenant_id: str
    user_id: str
    role_id: str
    expires_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class RoleDefinitionDTO:
    """Immutable projection of an `identity.roles` PBAC definition with explicit deny support."""

    id: str
    tenant_id: str
    name: str
    capabilities: frozenset[str]
    deny_capabilities: frozenset[str] = frozenset()
    is_system: bool = False


@dataclass(frozen=True, kw_only=True)
class PrincipalSnapshotDTO:
    """Bounded per-user snapshot cached in L1 LRU / L2 Redis and evicted via config-sync."""

    user_id: str
    status: UserStatus
    tokens_valid_after: datetime
    memberships: tuple[MembershipDTO, ...]
    role_assignments: tuple[UserRoleAssignmentDTO, ...]


@dataclass(frozen=True, kw_only=True)
class ResourceGrantDTO:
    """Immutable projection of an `identity.resource_grants` ReBAC relationship tuple."""

    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    relation: str
    subject_type: ResourceSubjectType
    subject_id: str
    effect: AuthzEffect = AuthzEffect.ALLOW
    expires_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class PolicyRuleDTO:
    """Immutable projection of an `identity.policy_rules` ABAC or Casbin rule."""

    id: str
    tenant_id: str
    engine_type: PolicyEngineType
    effect: AuthzEffect
    subject_expr: str
    resource_type: str
    action_pattern: str
    condition_json: JsonDict = field(default_factory=dict)
    priority: int = 100
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class ExternalIdentityDTO:
    """Immutable projection of an `identity.external_identities` link row."""

    id: str
    user_id: str
    idp_issuer: str
    idp_subject: str
    idp_realm_name: str | None = None
    linked_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class ExternalIdentityRef:
    """Provider-agnostic reference returned by IdentityProviderAdminPort user provisioning."""

    idp_issuer: str
    idp_subject: str
    idp_realm_name: str
    created: bool = True


@dataclass(frozen=True, kw_only=True)
class RealmRef:
    """Provider-agnostic reference returned by IdentityProviderAdminPort enterprise realm creation."""

    idp_issuer: str
    realm_name: str
    display_name: str


@dataclass(frozen=True, kw_only=True)
class EnterpriseSsoConfigDTO:
    """Provider-agnostic Enterprise SSO configuration for dedicated IdP realm provisioning."""

    protocol: str
    metadata_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    issuer_url: str | None = None
    email_domains: tuple[str, ...] = ()


__all__ = [
    "AuthzDecision",
    "AuthzRequest",
    "EmailDomainRouteDTO",
    "EnterpriseSsoConfigDTO",
    "ExternalIdentityDTO",
    "ExternalIdentityRef",
    "MembershipDTO",
    "PolicyRuleDTO",
    "PrincipalContext",
    "PrincipalSnapshotDTO",
    "RealmRef",
    "ResourceContext",
    "ResourceGrantDTO",
    "RoleDefinitionDTO",
    "TenantNodeDTO",
    "TrustedIssuerDTO",
    "UserRoleAssignmentDTO",
]
