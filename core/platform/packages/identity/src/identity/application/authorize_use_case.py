"""4-Layer Hybrid Local Policy Decision Point (PDP) implementing AuthorizationEnginePort."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog

from identity.domain.abac_evaluator import (
    evaluate_abac_ownership,
    evaluate_abac_policy_rules,
    evaluate_impersonation_guard,
    evaluate_m2m_guard,
)
from identity.domain.authorization import Capability, CapabilityDescriptor
from identity.domain.constants import (
    TOKEN_REVOCATION_CLOCK_SKEW_SECONDS,
    ActorType,
    AuthzEffect,
    AuthzObligation,
    AuthzReasonCode,
    UserStatus,
)
from identity.domain.dtos import (
    AuthzDecision,
    AuthzRequest,
    PrincipalContext,
    PrincipalSnapshotDTO,
    ResourceGrantDTO,
    RoleDefinitionDTO,
    TenantNodeDTO,
)
from identity.domain.hierarchy import (
    resolve_effective_role_ids,
    resolve_effective_tenant_scopes,
    resolve_inheritable_ancestors,
)
from identity.ports.outbound.authorization_engine_port import AuthorizationEnginePort
from identity.ports.outbound.policy_rule_repository_port import CasbinRuleEvaluatorPort
from identity.ports.outbound.principal_cache_port import PrincipalCachePort
from identity.ports.outbound.resource_grant_repository_port import ResourceGrantRepositoryPort
from identity.ports.outbound.tenant_entitlement_port import TenantEntitlementPort
from identity.ports.outbound.tenant_hierarchy_port import (
    AuthzDirectoryPort,
    GlobalAuthzCatalogPort,
)

logger = structlog.get_logger(__name__)

_CORE_CONTROL_PLANE_APPS: frozenset[str] = frozenset({"ucp", "platform", "identity"})

# Relation -> permitted action verb suffixes for fine-grained ReBAC resource grants
_RELATION_ACTION_VERBS: dict[str, frozenset[str]] = {
    "owner": frozenset({"read", "write", "delete", "execute", "admin", "manage"}),
    "editor": frozenset({"read", "write", "execute"}),
    "viewer": frozenset({"read"}),
    "commenter": frozenset({"read", "comment"}),
}


def _extract_email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", maxsplit=1)[1].strip().lower()
    return domain or None


def _is_token_revoked(token_issued_at: datetime, valid_after: datetime) -> bool:
    skew = timedelta(seconds=TOKEN_REVOCATION_CLOCK_SKEW_SECONDS)
    return (token_issued_at + skew) < valid_after


def _grant_allows_action(grant: ResourceGrantDTO, action: str) -> bool:
    if grant.relation == "*" or grant.relation == action:
        return True
    verbs = _RELATION_ACTION_VERBS.get(grant.relation.lower())
    if not verbs:
        return False
    action_verb = action.rsplit(":", maxsplit=1)[-1].lower()
    return action_verb in verbs


class HybridLocalAuthorizationEngine(AuthorizationEnginePort):
    """Sub-millisecond 4-Layer Local PDP with zero runtime HTTP calls to external IdPs.

    Evaluation order (fail-closed, AWS IAM semantics: Explicit Deny > Explicit Allow > Implicit Deny):
      Layer 1: Token revocation (iat vs tokens_valid_after + jti), tenant/user status,
               Enterprise SSO enforcement, M2M tenant pinning & scope intersection,
               break-glass impersonation invariants, App Subscription Gate, Step-Up MFA.
      Layer 2: Hierarchical ltree RBAC/PBAC with block_parent_inheritance & explicit DENY.
      Layer 3: Pure ABAC policy rules + O(1) B2C/Personal resource ownership.
      Layer 4: Indexed ReBAC resource grants + optional tenant-filtered Casbin rules.
    """

    def __init__(
        self,
        *,
        directory: AuthzDirectoryPort,
        global_catalog: GlobalAuthzCatalogPort,
        entitlements: TenantEntitlementPort,
        cache: PrincipalCachePort | None = None,
        resource_grants: ResourceGrantRepositoryPort | None = None,
        casbin_evaluator: CasbinRuleEvaluatorPort | None = None,
    ) -> None:
        self._directory = directory
        self._catalog = global_catalog
        self._entitlements = entitlements
        self._cache = cache
        self._resource_grants = resource_grants
        self._casbin = casbin_evaluator

    async def evaluate(self, request: AuthzRequest) -> AuthzDecision:
        started_ns = time.perf_counter_ns()
        now = request.now or datetime.now(UTC)

        decision = await self._evaluate_pipeline(request, now=now)
        elapsed_us = max(1, (time.perf_counter_ns() - started_ns) // 1000)
        final_decision = AuthzDecision(
            effect=decision.effect,
            reason_code=decision.reason_code,
            matched_policy_id=decision.matched_policy_id,
            obligations=decision.obligations,
            evaluated_in_us=elapsed_us,
        )
        self._emit_audit_log(request, final_decision)
        return final_decision

    async def _evaluate_layer1_prechecks(
        self, request: AuthzRequest, *, now: datetime
    ) -> tuple[AuthzDecision | None, tuple[TenantNodeDTO, ...]]:
        principal = request.principal

        if (
            principal.jti
            and self._cache is not None
            and await self._cache.is_jti_revoked(principal.jti)
        ):
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_TOKEN_REVOKED,
            ), ()

        imp_deny = evaluate_impersonation_guard(principal=principal, action=request.action, now=now)
        if imp_deny is not None:
            return imp_deny, ()

        sso_deny = self._check_enterprise_sso_enforcement(principal)
        if sso_deny is not None:
            return sso_deny, ()

        tenant_chain = await self._load_tenant_chain(request.tenant_id)
        if not tenant_chain:
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_TENANT_NOT_FOUND,
            ), ()

        tenant_deny = self._check_tenant_chain_health(tenant_chain, principal)
        if tenant_deny is not None:
            return tenant_deny, ()

        sub_deny = await self._check_app_subscription(request.tenant_id, request.app_slug)
        if sub_deny is not None:
            return sub_deny, ()

        return None, tenant_chain

    async def _evaluate_pipeline(self, request: AuthzRequest, *, now: datetime) -> AuthzDecision:
        precheck_deny, tenant_chain = await self._evaluate_layer1_prechecks(request, now=now)
        if precheck_deny is not None:
            return precheck_deny

        principal = request.principal
        capability = self._catalog.get_capability(request.action)

        if principal.actor_type in (ActorType.MACHINE, ActorType.SERVICE_ACCOUNT):
            m2m_deny = evaluate_m2m_guard(
                principal=principal,
                target_tenant_id=request.tenant_id,
                action=request.action,
                capability=capability,
            )
            return m2m_deny or AuthzDecision(
                effect=AuthzEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED_BY_CAPABILITY,
            )

        mfa_deny = self._check_step_up_mfa(principal, capability)
        if mfa_deny is not None:
            return mfa_deny

        snapshot = await self._load_principal_snapshot(principal.user_id)
        if snapshot is None or snapshot.status != UserStatus.ACTIVE:
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_ACCOUNT_SUSPENDED,
            )
        if _is_token_revoked(principal.token_issued_at, snapshot.tokens_valid_after):
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_TOKEN_REVOKED,
            )

        return await self._evaluate_layers_2_to_4(
            request=request,
            snapshot=snapshot,
            tenant_chain=tenant_chain,
            now=now,
        )

    @staticmethod
    def _first_allow(decisions: Sequence[AuthzDecision | None]) -> AuthzDecision | None:
        for decision in decisions:
            if decision is not None and decision.is_allowed:
                return decision
        return None

    async def _evaluate_layers_2_to_4(
        self,
        *,
        request: AuthzRequest,
        snapshot: PrincipalSnapshotDTO,
        tenant_chain: tuple[TenantNodeDTO, ...],
        now: datetime,
    ) -> AuthzDecision:
        nodes_by_id = {node.id: node for node in tenant_chain}
        inheritable_chain = resolve_inheritable_ancestors(
            nodes_by_id=nodes_by_id,
            target_tenant_id=request.tenant_id,
        )
        effective_tenants = resolve_effective_tenant_scopes(
            memberships=snapshot.memberships,
            inheritable_chain=inheritable_chain,
            target_tenant_id=request.tenant_id,
            now=now,
        )
        if not effective_tenants:
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_NOT_TENANT_MEMBER,
            )

        effective_role_ids = resolve_effective_role_ids(
            role_assignments=snapshot.role_assignments,
            effective_tenant_ids=effective_tenants,
            now=now,
        )
        role_id_set = frozenset(effective_role_ids)
        roles = await self._load_role_definitions(effective_role_ids)

        rbac_decision = self._evaluate_role_capabilities(roles, request.action)
        tenant_rules = self._catalog.get_tenant_policy_rules(request.tenant_id)
        abac_rule_decision = evaluate_abac_policy_rules(
            rules=tenant_rules,
            request=request,
            effective_role_ids=role_id_set,
        )
        rebac_decision = await self._evaluate_rebac_grants(
            request=request,
            role_ids=effective_role_ids,
            now=now,
        )

        # Explicit DENY from any layer unconditionally wins over Allow (AWS IAM semantics)
        for candidate in (rbac_decision, abac_rule_decision, rebac_decision):
            if candidate is not None and not candidate.is_allowed:
                return candidate

        ownership_decision = evaluate_abac_ownership(
            principal=request.principal,
            resource=request.resource,
            target_tenant_id=request.tenant_id,
        )
        allowed = self._first_allow(
            (rbac_decision, abac_rule_decision, ownership_decision, rebac_decision)
        )
        if allowed is not None:
            return allowed

        if self._casbin is not None and tenant_rules:
            casbin_decision = self._casbin.evaluate_casbin_rules(
                rules=tenant_rules,
                request=request,
                effective_role_ids=role_id_set,
            )
            if casbin_decision is not None:
                return casbin_decision

        return AuthzDecision(
            effect=AuthzEffect.DENY,
            reason_code=AuthzReasonCode.DENIED_MISSING_CAPABILITY,
        )

    def _check_enterprise_sso_enforcement(
        self, principal: PrincipalContext
    ) -> AuthzDecision | None:
        if principal.actor_type != ActorType.HUMAN:
            return None
        domain = _extract_email_domain(principal.email)
        if not domain:
            return None
        route = self._catalog.get_email_domain_route(domain)
        if route is None or not route.sso_enforced:
            return None
        issuer_matches = principal.idp_issuer.rstrip("/") == route.idp_issuer.rstrip("/")
        realm_matches = not route.idp_realm_name or principal.idp_realm == route.idp_realm_name
        if not (issuer_matches and realm_matches):
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_SSO_REQUIRED,
                obligations=(AuthzObligation.REDIRECT_ENTERPRISE_SSO,),
            )
        return None

    @staticmethod
    def _check_tenant_chain_health(
        tenant_chain: Sequence[TenantNodeDTO],
        principal: PrincipalContext,
    ) -> AuthzDecision | None:
        for node in tenant_chain:
            if node.status.lower() != "active":
                return AuthzDecision(
                    effect=AuthzEffect.DENY,
                    reason_code=AuthzReasonCode.DENIED_TENANT_SUSPENDED,
                )
            if _is_token_revoked(principal.token_issued_at, node.tokens_valid_after):
                return AuthzDecision(
                    effect=AuthzEffect.DENY,
                    reason_code=AuthzReasonCode.DENIED_TOKEN_REVOKED,
                )
        return None

    async def _check_app_subscription(self, tenant_id: str, app_slug: str) -> AuthzDecision | None:
        normalized_slug = app_slug.strip().lower()
        if not normalized_slug or normalized_slug in _CORE_CONTROL_PLANE_APPS:
            return None

        enabled_apps: frozenset[str] | None = None
        if self._cache is not None:
            enabled_apps = await self._cache.get_enabled_apps(tenant_id)
        if enabled_apps is None:
            enabled_apps = await self._entitlements.get_enabled_app_slugs(tenant_id=tenant_id)
            if self._cache is not None:
                await self._cache.set_enabled_apps(tenant_id, enabled_apps)

        if normalized_slug not in enabled_apps:
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_APP_NOT_SUBSCRIBED,
            )
        return None

    @staticmethod
    def _check_step_up_mfa(
        principal: PrincipalContext,
        capability: CapabilityDescriptor | None,
    ) -> AuthzDecision | None:
        if (
            principal.actor_type == ActorType.HUMAN
            and capability is not None
            and capability.requires_mfa
            and not principal.mfa_verified
        ):
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_STEP_UP_MFA_REQUIRED,
                obligations=(AuthzObligation.REQUIRE_MFA_STEP_UP,),
            )
        return None

    @staticmethod
    def _evaluate_role_capabilities(
        roles: Sequence[RoleDefinitionDTO],
        action: str,
    ) -> AuthzDecision | None:
        deny_caps: set[str] = set()
        allow_caps: set[str] = set()
        matched_deny_role: str | None = None
        matched_allow_role: str | None = None

        for role in roles:
            if action in role.deny_capabilities or "*" in role.deny_capabilities:
                deny_caps.add(action)
                matched_deny_role = role.id
            if (
                action in role.capabilities
                or Capability.PLATFORM_ADMIN.value in role.capabilities
                or (
                    Capability.TENANT_ADMIN.value in role.capabilities
                    and action != Capability.PLATFORM_ADMIN.value
                )
            ):
                allow_caps.add(action)
                if matched_allow_role is None:
                    matched_allow_role = role.id

        if action in deny_caps:
            return AuthzDecision(
                effect=AuthzEffect.DENY,
                reason_code=AuthzReasonCode.DENIED_EXPLICIT_POLICY,
                matched_policy_id=matched_deny_role,
            )
        if action in allow_caps:
            return AuthzDecision(
                effect=AuthzEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED_BY_CAPABILITY,
                matched_policy_id=matched_allow_role,
            )
        return None

    async def _evaluate_rebac_grants(
        self,
        *,
        request: AuthzRequest,
        role_ids: Sequence[str],
        now: datetime,
    ) -> AuthzDecision | None:
        if (
            self._resource_grants is None
            or request.resource is None
            or not request.resource.resource_id
        ):
            return None

        grants = await self._resource_grants.find_matching_grants(
            tenant_id=request.tenant_id,
            resource_type=request.resource.resource_type,
            resource_id=request.resource.resource_id,
            user_id=request.principal.user_id,
            role_ids=role_ids,
        )
        allow_grant: ResourceGrantDTO | None = None
        for grant in grants:
            if grant.expires_at is not None and grant.expires_at <= now:
                continue
            if not _grant_allows_action(grant, request.action):
                continue
            if grant.effect == AuthzEffect.DENY:
                return AuthzDecision(
                    effect=AuthzEffect.DENY,
                    reason_code=AuthzReasonCode.DENIED_EXPLICIT_POLICY,
                    matched_policy_id=grant.id,
                )
            if allow_grant is None:
                allow_grant = grant

        if allow_grant is not None:
            return AuthzDecision(
                effect=AuthzEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED_BY_RESOURCE_GRANT,
                matched_policy_id=allow_grant.id,
            )
        return None

    async def _load_principal_snapshot(self, user_id: str) -> PrincipalSnapshotDTO | None:
        if self._cache is not None:
            cached = await self._cache.get_principal(user_id)
            if cached is not None:
                return cached
        snapshot = await self._directory.get_principal_snapshot(user_id=user_id)
        if snapshot is not None and self._cache is not None:
            await self._cache.set_principal(snapshot)
        return snapshot

    async def _load_tenant_chain(self, tenant_id: str) -> tuple[TenantNodeDTO, ...]:
        if self._cache is not None:
            cached_leaf = await self._cache.get_tenant_node(tenant_id)
            if cached_leaf is not None and cached_leaf.parent_tenant_id is None:
                return (cached_leaf,)
        chain = await self._directory.get_tenant_ancestor_chain(tenant_id=tenant_id)
        if chain and self._cache is not None:
            for node in chain:
                await self._cache.set_tenant_node(node)
        return chain

    async def _load_role_definitions(
        self, role_ids: Sequence[str]
    ) -> tuple[RoleDefinitionDTO, ...]:
        resolved: dict[str, RoleDefinitionDTO] = {}
        missing: list[str] = []
        for role_id in role_ids:
            platform_role = self._catalog.get_platform_role(role_id)
            if platform_role is not None:
                resolved[role_id] = platform_role
                continue
            if self._cache is not None:
                cached = await self._cache.get_role_definition(role_id)
                if cached is not None:
                    resolved[role_id] = cached
                    continue
            missing.append(role_id)

        if missing:
            fetched = await self._directory.get_roles_by_ids(role_ids=missing)
            for rid, role_def in fetched.items():
                resolved[rid] = role_def
                if self._cache is not None:
                    await self._cache.set_role_definition(role_def)

        return tuple(resolved[rid] for rid in role_ids if rid in resolved)

    @staticmethod
    def _emit_audit_log(request: AuthzRequest, decision: AuthzDecision) -> None:
        principal = request.principal
        if not decision.is_allowed:
            logger.error(
                "authz.denied",
                actor_id=principal.user_id,
                actor_type=principal.actor_type.value,
                impersonator_id=principal.impersonator_user_id,
                ticket_id=principal.impersonation_ticket_id,
                tenant_id=request.tenant_id,
                app_slug=request.app_slug,
                action=request.action,
                reason_code=decision.reason_code.value,
                matched_policy_id=decision.matched_policy_id,
                evaluated_in_us=decision.evaluated_in_us,
            )
            return

        if principal.actor_type == ActorType.DELEGATED_SUPPORT:
            logger.info(
                "authz.granted.impersonated",
                actor_id=principal.user_id,
                impersonator_id=principal.impersonator_user_id,
                ticket_id=principal.impersonation_ticket_id,
                tenant_id=request.tenant_id,
                app_slug=request.app_slug,
                action=request.action,
                reason_code=decision.reason_code.value,
                evaluated_in_us=decision.evaluated_in_us,
            )


__all__ = ["HybridLocalAuthorizationEngine"]
