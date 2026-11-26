"""In-memory low-cardinality GlobalAuthzCatalogPort store updated atomically via config-sync."""

from __future__ import annotations

from collections.abc import Iterable

from identity.domain.authorization import CapabilityDescriptor
from identity.domain.dtos import (
    EmailDomainRouteDTO,
    PolicyRuleDTO,
    RoleDefinitionDTO,
    TrustedIssuerDTO,
)
from identity.ports.outbound.tenant_hierarchy_port import MutableGlobalAuthzCatalogPort


class InMemoryGlobalAuthzCatalog(MutableGlobalAuthzCatalogPort):
    """Stores strictly low-cardinality global IAM metadata (< 50K rows total, ~5-10MB RAM)."""

    def __init__(
        self,
        *,
        trusted_issuers: Iterable[TrustedIssuerDTO] = (),
        capabilities: Iterable[CapabilityDescriptor] = (),
        email_domain_routes: Iterable[EmailDomainRouteDTO] = (),
        platform_roles: Iterable[RoleDefinitionDTO] = (),
        policy_rules: Iterable[PolicyRuleDTO] = (),
    ) -> None:
        self._trusted_issuers: dict[str, TrustedIssuerDTO] = {
            item.issuer.rstrip("/"): item for item in trusted_issuers
        }
        self._capabilities: dict[str, CapabilityDescriptor] = {
            cap.code: cap for cap in capabilities
        }
        self._email_routes: dict[str, EmailDomainRouteDTO] = {
            route.domain.strip().lower(): route for route in email_domain_routes
        }
        self._platform_roles: dict[str, RoleDefinitionDTO] = {
            role.id: role for role in platform_roles
        }
        self._policy_rules_by_tenant: dict[str, dict[str, PolicyRuleDTO]] = {}
        for rule in policy_rules:
            self._policy_rules_by_tenant.setdefault(rule.tenant_id, {})[rule.id] = rule

    def get_trusted_issuer(self, issuer: str) -> TrustedIssuerDTO | None:
        return self._trusted_issuers.get(issuer.rstrip("/"))

    def list_trusted_issuers(self) -> tuple[TrustedIssuerDTO, ...]:
        return tuple(self._trusted_issuers.values())

    def get_capability(self, code: str) -> CapabilityDescriptor | None:
        return self._capabilities.get(code)

    def get_email_domain_route(self, domain: str) -> EmailDomainRouteDTO | None:
        return self._email_routes.get(domain.strip().lower())

    def get_platform_role(self, role_id: str) -> RoleDefinitionDTO | None:
        return self._platform_roles.get(role_id)

    def get_tenant_policy_rules(self, tenant_id: str) -> tuple[PolicyRuleDTO, ...]:
        rules = self._policy_rules_by_tenant.get(tenant_id)
        if not rules:
            return ()
        return tuple(rules.values())

    # Atomic upsert/delete helpers invoked by IdentityInvalidationSink on config-sync SSE deltas
    def upsert_trusted_issuer(self, issuer: TrustedIssuerDTO) -> None:
        self._trusted_issuers[issuer.issuer.rstrip("/")] = issuer

    def remove_trusted_issuer(self, issuer: str) -> None:
        self._trusted_issuers.pop(issuer.rstrip("/"), None)

    def upsert_capability(self, capability: CapabilityDescriptor) -> None:
        self._capabilities[capability.code] = capability

    def upsert_email_domain_route(self, route: EmailDomainRouteDTO) -> None:
        self._email_routes[route.domain.strip().lower()] = route

    def remove_email_domain_route(self, domain: str) -> None:
        self._email_routes.pop(domain.strip().lower(), None)

    def upsert_platform_role(self, role: RoleDefinitionDTO) -> None:
        self._platform_roles[role.id] = role

    def remove_platform_role(self, role_id: str) -> None:
        self._platform_roles.pop(role_id, None)

    def upsert_policy_rule(self, rule: PolicyRuleDTO) -> None:
        self._policy_rules_by_tenant.setdefault(rule.tenant_id, {})[rule.id] = rule

    def remove_policy_rule(self, *, tenant_id: str, rule_id: str) -> None:
        bucket = self._policy_rules_by_tenant.get(tenant_id)
        if bucket is not None:
            bucket.pop(rule_id, None)


__all__ = ["InMemoryGlobalAuthzCatalog"]
