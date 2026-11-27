"""Open-Closed Application Use Case and composable resolvers for Home Realm Discovery (HRD)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import structlog

from identity.domain.dtos import HomeRealmDecisionDTO
from identity.ports.outbound.home_realm_resolver_port import (
    FallbackHomeRealmResolverPort,
    HomeRealmResolverPort,
)
from identity.ports.outbound.tenant_hierarchy_port import GlobalAuthzCatalogPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ResolveHomeRealmCommand:
    """Pure CQRS command for Home Realm Discovery."""

    email: str


class EnterpriseHomeRealmResolver:
    """Resolves verified enterprise email domains to their dedicated tenant realm/SSO issuer."""

    def __init__(
        self,
        *,
        global_catalog: GlobalAuthzCatalogPort | None,
        default_issuer: str,
        client_id_for_realm: Callable[[str], str],
    ) -> None:
        self._catalog = global_catalog
        self._default_issuer = default_issuer
        self._client_id_for_realm = client_id_for_realm

    @property
    def name(self) -> str:
        return "enterprise"

    def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO | None:
        if not domain or self._catalog is None:
            return None
        route = self._catalog.get_email_domain_route(domain)
        if route is None or route.verified_at is None:
            return None
        return HomeRealmDecisionDTO(
            realm=route.idp_realm_name,
            issuer=route.idp_issuer or self._default_issuer,
            client_id=self._client_id_for_realm(route.idp_realm_name),
            require_sso=route.sso_enforced,
            sso_provider=None,
            tenant_id=route.tenant_id,
            login_hint=email or None,
        )


class PlatformHomeRealmResolver:
    """Resolves verified internal operator domains to the isolated platform realm/client."""

    def __init__(
        self,
        *,
        platform_domains: frozenset[str],
        platform_realm: str,
        issuer: str,
        client_id: str,
    ) -> None:
        self._platform_domains = frozenset(d.strip().lower() for d in platform_domains if d.strip())
        self._platform_realm = platform_realm
        self._issuer = issuer
        self._client_id = client_id

    @property
    def name(self) -> str:
        return "platform"

    def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO | None:
        if not domain or not self._client_id or domain not in self._platform_domains:
            return None
        return HomeRealmDecisionDTO(
            realm=self._platform_realm,
            issuer=self._issuer,
            client_id=self._client_id,
            require_sso=False,
            sso_provider=None,
            tenant_id=None,
            login_hint=email or None,
        )


class GlobalHomeRealmResolver:
    """Unconditional fallback resolver targeting the pooled global realm (anti-enumeration)."""

    def __init__(
        self,
        *,
        global_realm: str,
        issuer: str,
        client_id: str,
    ) -> None:
        self._global_realm = global_realm
        self._issuer = issuer
        self._client_id = client_id

    @property
    def name(self) -> str:
        return "global"

    def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO:
        del domain
        return HomeRealmDecisionDTO(
            realm=self._global_realm,
            issuer=self._issuer,
            client_id=self._client_id,
            require_sso=False,
            sso_provider=None,
            tenant_id=None,
            login_hint=email or None,
        )


class ResolveHomeRealmUseCase:
    """Composable Chain-of-Responsibility Use Case for Home Realm Discovery.

    New routing policies (e.g., partner white-label domains, sovereign regions,
    invitation tokens) plug into ``resolvers`` without modifying this class.
    """

    def __init__(
        self,
        *,
        resolvers: Sequence[HomeRealmResolverPort],
        fallback: FallbackHomeRealmResolverPort,
    ) -> None:
        self._resolvers = tuple(resolvers)
        self._fallback = fallback

    def execute(self, command: ResolveHomeRealmCommand) -> HomeRealmDecisionDTO:
        normalized_email = command.email.strip().lower()
        domain = normalized_email.rsplit("@", 1)[-1] if "@" in normalized_email else ""

        for resolver in self._resolvers:
            decision = resolver.resolve(email=normalized_email, domain=domain)
            if decision is not None:
                logger.info(
                    "auth_hrd_resolved",
                    domain=domain,
                    realm=decision.realm,
                    require_sso=decision.require_sso,
                    resolver=resolver.name,
                )
                return decision

        fallback_decision = self._fallback.resolve(email=normalized_email, domain=domain)
        logger.info(
            "auth_hrd_resolved",
            domain=domain or self._fallback.name,
            realm=fallback_decision.realm,
            require_sso=fallback_decision.require_sso,
            resolver=self._fallback.name,
        )
        return fallback_decision
