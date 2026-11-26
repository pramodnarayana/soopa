"""Outbound ports for bounded tenant hierarchy lookups and low-cardinality global IAM catalog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from identity.domain.authorization import CapabilityDescriptor
from identity.domain.dtos import (
    EmailDomainRouteDTO,
    PolicyRuleDTO,
    PrincipalSnapshotDTO,
    RoleDefinitionDTO,
    TenantNodeDTO,
    TrustedIssuerDTO,
)


class AuthzDirectoryPort(Protocol):
    """High-cardinality directory lookups backed by covering indexes (never loaded globally into RAM)."""

    async def get_principal_snapshot(self, *, user_id: str) -> PrincipalSnapshotDTO | None: ...

    async def get_tenant_ancestor_chain(self, *, tenant_id: str) -> tuple[TenantNodeDTO, ...]: ...

    async def get_roles_by_ids(
        self, *, role_ids: Sequence[str]
    ) -> dict[str, RoleDefinitionDTO]: ...


class GlobalAuthzCatalogPort(Protocol):
    """Low-cardinality global IAM metadata kept in RAM via config-sync (< 50K rows total)."""

    def get_trusted_issuer(self, issuer: str) -> TrustedIssuerDTO | None: ...

    def list_trusted_issuers(self) -> tuple[TrustedIssuerDTO, ...]: ...

    def get_capability(self, code: str) -> CapabilityDescriptor | None: ...

    def get_email_domain_route(self, domain: str) -> EmailDomainRouteDTO | None: ...

    def get_platform_role(self, role_id: str) -> RoleDefinitionDTO | None: ...

    def get_tenant_policy_rules(self, tenant_id: str) -> tuple[PolicyRuleDTO, ...]: ...


class MutableGlobalAuthzCatalogPort(GlobalAuthzCatalogPort, Protocol):
    """Write-side port for updating the low-cardinality global IAM RAM catalog."""

    def upsert_trusted_issuer(self, issuer: TrustedIssuerDTO) -> None: ...

    def remove_trusted_issuer(self, issuer: str) -> None: ...

    def upsert_capability(self, capability: CapabilityDescriptor) -> None: ...

    def upsert_email_domain_route(self, route: EmailDomainRouteDTO) -> None: ...

    def remove_email_domain_route(self, domain: str) -> None: ...

    def upsert_platform_role(self, role: RoleDefinitionDTO) -> None: ...

    def remove_platform_role(self, role_id: str) -> None: ...

    def upsert_policy_rule(self, rule: PolicyRuleDTO) -> None: ...

    def remove_policy_rule(self, *, tenant_id: str, rule_id: str) -> None: ...


__all__ = ["AuthzDirectoryPort", "GlobalAuthzCatalogPort", "MutableGlobalAuthzCatalogPort"]
