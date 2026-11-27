"""Pure ABAC, M2M, Impersonation, and Ownership policy evaluators (zero I/O, zero mocks)."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from datetime import datetime
from fnmatch import fnmatch

from identity.domain.authorization import Capability, CapabilityDescriptor
from identity.domain.constants import (
    MAX_IMPERSONATION_TTL_SECONDS,
    ActorType,
    AuthzEffect,
    AuthzReasonCode,
    PolicyEngineType,
    ResourceClassification,
)
from identity.domain.dtos import (
    AuthzDecision,
    AuthzRequest,
    PolicyRuleDTO,
    PrincipalContext,
    ResourceContext,
)

# Actions strictly prohibited during break-glass support impersonation
_IMPERSONATION_FORBIDDEN_ACTIONS: frozenset[str] = frozenset(
    {
        Capability.PLATFORM_ADMIN.value,
        Capability.PLATFORM_IMPERSONATE.value,
        Capability.ROLES_WRITE.value,
        Capability.API_KEYS_WRITE.value,
        Capability.USERS_WRITE.value,
    }
)


def evaluate_impersonation_guard(
    *,
    principal: PrincipalContext,
    action: str,
    now: datetime,
) -> AuthzDecision | None:
    """Enforce mandatory security invariants for `DELEGATED_SUPPORT` impersonation sessions.

    Returns a DENY `AuthzDecision` if any invariant is violated, or `None` if valid.
    """
    if principal.actor_type != ActorType.DELEGATED_SUPPORT:
        return None

    if not principal.impersonator_user_id or not principal.impersonation_ticket_id:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_IMPERSONATION_POLICY,
        )

    if not principal.mfa_verified:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_IMPERSONATION_POLICY,
        )

    if principal.impersonation_expires_at is None:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_IMPERSONATION_POLICY,
        )

    if principal.impersonation_expires_at <= now:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_TOKEN_REVOKED,
        )

    ttl_seconds = (principal.impersonation_expires_at - principal.token_issued_at).total_seconds()
    if ttl_seconds > MAX_IMPERSONATION_TTL_SECONDS:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_IMPERSONATION_POLICY,
        )

    if action in _IMPERSONATION_FORBIDDEN_ACTIONS:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_IMPERSONATION_POLICY,
        )

    return None


def evaluate_m2m_guard(
    *,
    principal: PrincipalContext,
    target_tenant_id: str,
    action: str,
    capability: CapabilityDescriptor | None,
) -> AuthzDecision | None:
    """Enforce fail-closed tenant pinning, machine capability eligibility, and scope intersection."""
    if principal.actor_type not in (ActorType.MACHINE, ActorType.SERVICE_ACCOUNT):
        return None

    if not principal.bound_tenant_id or principal.bound_tenant_id != target_tenant_id:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_TENANT_SCOPE_MISMATCH,
        )

    if capability is not None and not capability.machine_allowed:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_MACHINE_ACTION_FORBIDDEN,
        )

    if principal.token_scopes is None:
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_MISSING_CAPABILITY,
        )

    if "*" in principal.token_scopes:
        return None

    if not any(fnmatch(action, scope) for scope in principal.token_scopes):
        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_MISSING_CAPABILITY,
        )

    return None


def evaluate_abac_ownership(
    *,
    principal: PrincipalContext,
    resource: ResourceContext | None,
    target_tenant_id: str,
) -> AuthzDecision | None:
    """O(1) consumer/personal resource ownership check (zero DB, zero Casbin bloat).

    Returns ALLOW when the principal owns the resource within the same tenant; otherwise `None`.
    """
    if resource is None or not resource.owner_user_id:
        return None
    if resource.tenant_id is not None and resource.tenant_id != target_tenant_id:
        return None
    if resource.owner_user_id == principal.user_id:
        return AuthzDecision(
            effect=AuthzEffect.ALLOW,
            reason_code=AuthzReasonCode.ALLOWED_BY_ABAC_OWNERSHIP,
        )
    return None


def _matches_ip_cidrs(client_ip: str | None, allowed_cidrs: Sequence[str]) -> bool:
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for raw_cidr in allowed_cidrs:
        try:
            network = ipaddress.ip_network(raw_cidr, strict=False)
        except ValueError:
            continue
        if addr in network:
            return True
    return False


def _matches_resource_attributes(raw_attrs: object, resource: ResourceContext | None) -> bool:
    if not isinstance(raw_attrs, dict):
        return True
    if resource is None:
        return False
    return all(resource.attributes.get(str(k)) == v for k, v in raw_attrs.items())


def _rule_matches_conditions(rule: PolicyRuleDTO, request: AuthzRequest) -> bool:
    cond = rule.condition_json
    if not cond:
        return True

    require_mfa = cond.get("require_mfa")
    if isinstance(require_mfa, bool) and require_mfa != request.principal.mfa_verified:
        return False

    raw_classification = cond.get("classification")
    actual_cls = (
        request.resource.classification.value
        if request.resource is not None
        else ResourceClassification.STANDARD.value
    )
    if isinstance(raw_classification, str) and actual_cls != raw_classification:
        return False

    raw_cidrs = cond.get("allowed_cidrs")
    if isinstance(raw_cidrs, list):
        cidrs = [str(c) for c in raw_cidrs if isinstance(c, str)]
        if cidrs and not _matches_ip_cidrs(request.client_ip, cidrs):
            return False

    return _matches_resource_attributes(cond.get("resource_attributes"), request.resource)


def _rule_matches_subject(
    subject_expr: str, principal: PrincipalContext, role_ids: frozenset[str]
) -> bool:
    if subject_expr == "*":
        return True
    if subject_expr == f"user:{principal.user_id}":
        return True
    if subject_expr.startswith("role:"):
        return subject_expr[5:] in role_ids
    if subject_expr.startswith("actor:"):
        return subject_expr[6:] == principal.actor_type.value
    return False


def evaluate_abac_policy_rules(
    *,
    rules: Sequence[PolicyRuleDTO],
    request: AuthzRequest,
    effective_role_ids: frozenset[str],
) -> AuthzDecision | None:
    """Evaluate active tenant ABAC policy rules using AWS IAM semantics (Explicit Deny > Allow)."""
    resource_type = request.resource.resource_type if request.resource is not None else "*"
    sorted_rules = sorted(
        (r for r in rules if r.is_active and r.engine_type == PolicyEngineType.ABAC),
        key=lambda r: r.priority,
    )

    first_allow: PolicyRuleDTO | None = None
    for rule in sorted_rules:
        if not fnmatch(resource_type, rule.resource_type):
            continue
        if not fnmatch(request.action, rule.action_pattern):
            continue
        if not _rule_matches_subject(rule.subject_expr, request.principal, effective_role_ids):
            continue
        if not _rule_matches_conditions(rule, request):
            continue
        if rule.effect == AuthzEffect.DENY:
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_EXPLICIT_POLICY,
                matched_policy_id=rule.id,
            )
        if first_allow is None:
            first_allow = rule

    if first_allow is not None:
        return AuthzDecision(
            effect=AuthzEffect.ALLOW,
            reason_code=AuthzReasonCode.ALLOWED_BY_CAPABILITY,
            matched_policy_id=first_allow.id,
        )
    return None


__all__ = [
    "evaluate_abac_ownership",
    "evaluate_abac_policy_rules",
    "evaluate_impersonation_guard",
    "evaluate_m2m_guard",
]
