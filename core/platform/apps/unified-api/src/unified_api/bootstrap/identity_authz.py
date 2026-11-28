"""Composition Root assembly for the Gold-Standard Identity & Local 4-Layer PDP."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import structlog
from database.models.identity import (
    Capability as OrmCapability,
)
from database.models.identity import (
    EmailDomainRoute as OrmEmailDomainRoute,
)
from database.models.identity import (
    PolicyRule as OrmPolicyRule,
)
from database.models.identity import (
    Role as OrmRole,
)
from database.models.identity import (
    TrustedIssuer as OrmTrustedIssuer,
)
from database.provider import DatabaseProvider
from database.utils import DATABASE_CONNECTION_ERRORS
from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.adapters.outbound.cache.l1_lru_principal_cache import L1LruPrincipalCache
from identity.adapters.outbound.config_sync.identity_invalidation_sink import (
    IdentityInvalidationSink,
)
from identity.adapters.outbound.database.authz_directory_repository import (
    SqlAlchemyAuthzDirectoryRepository,
)
from identity.adapters.outbound.database.resource_grant_repository import (
    SqlAlchemyResourceGrantRepository,
)
from identity.application.authorize_use_case import HybridLocalAuthorizationEngine
from identity.application.resolve_home_realm_use_case import (
    EnterpriseHomeRealmResolver,
    GlobalHomeRealmResolver,
    PlatformHomeRealmResolver,
    ResolveHomeRealmUseCase,
)
from identity.config import PlatformIdentitySettings
from identity.domain.authorization import CapabilityDescriptor
from identity.domain.constants import AuthzEffect, PolicyEngineType
from identity.domain.dtos import (
    EmailDomainRouteDTO,
    PolicyRuleDTO,
    RoleDefinitionDTO,
    TrustedIssuerDTO,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.ports.outbound.authorization_engine_port import (
    AuthorizationEnginePort,
    AuthzRuntimePort,
)
from identity.ports.outbound.tenant_entitlement_port import TenantEntitlementPort
from identity.ports.outbound.token_verifier_port import TokenVerifierPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.adapters.outbound.database.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
)
from ucp.bootstrap.dependencies import build_token_verifier

logger = structlog.get_logger(__name__)


@dataclass
class SlidingWindowRateLimiter:
    """Bounded per-key sliding-window rate limiter protecting public auth endpoints."""

    max_requests: int = 30
    window_seconds: float = 60.0
    max_keys: int = 10_000
    _buckets: dict[str, deque[float]] = field(default_factory=dict)

    def check_and_record(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        """Returns ``(allowed, retry_after_seconds)`` without throwing exceptions."""
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds

        if key not in self._buckets and len(self._buckets) >= self.max_keys:
            oldest_key = next(iter(self._buckets))
            del self._buckets[oldest_key]

        bucket = self._buckets.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            retry_after = max(1, int(bucket[0] + self.window_seconds - current) + 1)
            return False, retry_after

        bucket.append(current)
        return True, 0


def build_home_realm_use_case(
    *,
    settings: PlatformIdentitySettings,
    global_catalog: InMemoryGlobalAuthzCatalog,
) -> ResolveHomeRealmUseCase:
    """Composition Root factory assembling the Open-Closed HRD resolver chain."""
    return ResolveHomeRealmUseCase(
        resolvers=(
            EnterpriseHomeRealmResolver(
                global_catalog=global_catalog,
                default_issuer=settings.issuer,
                client_id_for_realm=settings.resolve_realm_client_id,
            ),
            PlatformHomeRealmResolver(
                platform_domains=settings.platform_admin_domains,
                platform_realm=settings.platform_realm,
                issuer=settings.issuer,
                client_id=settings.platform_admin_client_id,
            ),
        ),
        fallback=GlobalHomeRealmResolver(
            global_realm=settings.global_realm,
            issuer=settings.issuer,
            client_id=settings.resolve_realm_client_id(settings.global_realm),
        ),
    )


@dataclass(frozen=True)
class IdentityAuthzRuntime(AuthzRuntimePort[AsyncSession]):
    """In-process Gold-Standard Identity & Authorization runtime attached to `app.state`."""

    global_catalog: InMemoryGlobalAuthzCatalog
    principal_cache: L1LruPrincipalCache
    invalidation_sink: IdentityInvalidationSink
    token_verifier: TokenVerifierPort
    home_realm_use_case: ResolveHomeRealmUseCase
    hrd_rate_limiter: SlidingWindowRateLimiter

    def build_entitlements(self, session: AsyncSession) -> TenantEntitlementPort:
        """Assemble the request-scoped TenantEntitlementPort adapter via the Composition Root."""
        return SqlAlchemyTenantEntitlementRepository(session)

    def _build_local_pdp(self, session: AsyncSession) -> HybridLocalAuthorizationEngine:
        return HybridLocalAuthorizationEngine(
            directory=SqlAlchemyAuthzDirectoryRepository(session),
            global_catalog=self.global_catalog,
            entitlements=SqlAlchemyTenantEntitlementRepository(session),
            cache=self.principal_cache,
            resource_grants=SqlAlchemyResourceGrantRepository(session),
        )

    def build_engine(self, session: AsyncSession) -> AuthorizationEnginePort:
        """Assemble a request-scoped 4-Layer Local PDP sharing the bounded L1 cache & global catalog."""
        return self._build_local_pdp(session)

    async def has_hierarchical_tenant_access(
        self,
        *,
        session: AsyncSession,
        user_id: str,
        target_tenant_id: str,
    ) -> bool:
        """Delegate hierarchical `ltree` & tenant-health check to the shared 4-Layer Local PDP."""
        return await self._build_local_pdp(session).has_active_tenant_access(
            user_id=user_id,
            target_tenant_id=target_tenant_id,
        )


def create_identity_authz_runtime(settings: PlatformIdentitySettings) -> IdentityAuthzRuntime:
    """Create the bounded L1 cache, low-cardinality global catalog, invalidation sink, HRD use case, and OIDC verifier."""
    global_catalog = InMemoryGlobalAuthzCatalog()
    principal_cache = L1LruPrincipalCache(
        max_principals=settings.l1_cache_max_entries,
        ttl_seconds=float(settings.l1_cache_ttl_seconds),
    )
    invalidation_sink = IdentityInvalidationSink(
        principal_cache=principal_cache,
        global_catalog=global_catalog,
    )
    token_verifier = build_token_verifier(global_catalog=global_catalog)
    home_realm_use_case = build_home_realm_use_case(
        settings=settings,
        global_catalog=global_catalog,
    )
    hrd_rate_limiter = SlidingWindowRateLimiter()
    return IdentityAuthzRuntime(
        global_catalog=global_catalog,
        principal_cache=principal_cache,
        invalidation_sink=invalidation_sink,
        token_verifier=token_verifier,
        home_realm_use_case=home_realm_use_case,
        hrd_rate_limiter=hrd_rate_limiter,
    )


async def warm_global_authz_catalog(
    *,
    db_provider: DatabaseProvider,
    catalog: InMemoryGlobalAuthzCatalog,
) -> None:
    """Load the tiny (< 1 MB) low-cardinality global IAM catalog from PostgreSQL at startup."""
    try:
        async with db_provider.session() as session:
            issuer_rows = (
                (
                    await session.execute(
                        select(OrmTrustedIssuer).where(OrmTrustedIssuer.is_active.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            for issuer_row in issuer_rows:
                catalog.upsert_trusted_issuer(
                    TrustedIssuerDTO(
                        issuer=issuer_row.issuer.strip().rstrip("/"),
                        jwks_uri=issuer_row.jwks_uri,
                        allowed_audiences=tuple(issuer_row.allowed_audiences or ()),
                        jwks_host_header=issuer_row.jwks_host_header,
                        is_active=issuer_row.is_active,
                    )
                )

            route_rows = (await session.execute(select(OrmEmailDomainRoute))).scalars().all()
            for route_row in route_rows:
                catalog.upsert_email_domain_route(
                    EmailDomainRouteDTO(
                        domain=route_row.domain.strip().lower(),
                        tenant_id=route_row.tenant_id,
                        idp_issuer=route_row.idp_issuer,
                        idp_realm_name=route_row.idp_realm_name,
                        sso_enforced=route_row.sso_enforced,
                        verified_at=route_row.verified_at,
                    )
                )

            cap_rows = (await session.execute(select(OrmCapability))).scalars().all()
            for cap_row in cap_rows:
                catalog.upsert_capability(
                    CapabilityDescriptor(
                        code=cap_row.code,
                        domain=cap_row.domain,
                        resource=cap_row.resource,
                        action=cap_row.action,
                        display_name=cap_row.display_name,
                        description=cap_row.description,
                        is_sensitive=cap_row.is_sensitive,
                        requires_mfa=cap_row.requires_mfa,
                        machine_allowed=cap_row.machine_allowed,
                        tier_scope=cap_row.tier_scope,
                    )
                )

            role_rows = (
                (
                    await session.execute(
                        select(OrmRole).where(
                            OrmRole.tenant_id == PLATFORM_TENANT_ID,
                            OrmRole.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for role_row in role_rows:
                catalog.upsert_platform_role(
                    RoleDefinitionDTO(
                        id=role_row.id,
                        tenant_id=role_row.tenant_id or PLATFORM_TENANT_ID,
                        name=role_row.name,
                        capabilities=frozenset(role_row.capabilities or ()),
                        deny_capabilities=frozenset(role_row.deny_capabilities or ()),
                        is_system=role_row.is_system,
                    )
                )

            rule_rows = (
                (
                    await session.execute(
                        select(OrmPolicyRule).where(
                            OrmPolicyRule.tenant_id == PLATFORM_TENANT_ID,
                            OrmPolicyRule.is_active.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for rule_row in rule_rows:
                catalog.upsert_policy_rule(
                    PolicyRuleDTO(
                        id=rule_row.id,
                        tenant_id=rule_row.tenant_id,
                        engine_type=PolicyEngineType(rule_row.engine_type),
                        effect=AuthzEffect(rule_row.effect),
                        subject_expr=rule_row.subject_expr,
                        resource_type=rule_row.resource_type,
                        action_pattern=rule_row.action_pattern,
                        condition_json=dict(rule_row.condition_json or {}),
                        priority=rule_row.priority,
                        is_active=rule_row.is_active,
                    )
                )

        logger.info(
            "identity_global_authz_catalog_warmed",
            trusted_issuers=len(issuer_rows),
            email_domain_routes=len(route_rows),
            capabilities=len(cap_rows),
            platform_roles=len(role_rows),
            policy_rules=len(rule_rows),
        )
    except DATABASE_CONNECTION_ERRORS:
        logger.exception("identity_global_authz_catalog_warm_failed")


__all__ = [
    "IdentityAuthzRuntime",
    "SlidingWindowRateLimiter",
    "build_home_realm_use_case",
    "create_identity_authz_runtime",
    "warm_global_authz_catalog",
]
