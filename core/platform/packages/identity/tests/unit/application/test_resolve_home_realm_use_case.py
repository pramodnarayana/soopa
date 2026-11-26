"""Behavioral unit tests for Home Realm Discovery (HRD) security and routing invariants."""

from __future__ import annotations

from datetime import UTC, datetime

from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.application.resolve_home_realm_use_case import (
    EnterpriseHomeRealmResolver,
    GlobalHomeRealmResolver,
    PlatformHomeRealmResolver,
    ResolveHomeRealmCommand,
    ResolveHomeRealmUseCase,
)
from identity.domain.dtos import EmailDomainRouteDTO, HomeRealmDecisionDTO


class _PartnerWhiteLabelResolver:
    """Custom Open-Closed resolver verifying pluggable Chain-of-Responsibility ordering."""

    @property
    def name(self) -> str:
        return "partner_white_label"

    def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO | None:
        if domain != "partner.example":
            return None
        return HomeRealmDecisionDTO(
            realm="partner-eu",
            issuer="https://idp.partner.example",
            client_id="partner-client-eu",
            require_sso=True,
            sso_provider="okta",
            tenant_id="tenant-partner-1",
            login_hint=email,
        )


def _build_use_case(
    *,
    catalog: InMemoryGlobalAuthzCatalog | None,
    platform_domains: frozenset[str] = frozenset({"soopa.io"}),
    platform_client_id: str = "soopa-platform-admin",
) -> ResolveHomeRealmUseCase:
    return ResolveHomeRealmUseCase(
        resolvers=(
            EnterpriseHomeRealmResolver(
                global_catalog=catalog,
                default_issuer="https://auth.soopa.local",
                client_id_for_realm=lambda realm: f"client-{realm}",
            ),
            PlatformHomeRealmResolver(
                platform_domains=platform_domains,
                platform_realm="soopa-platform",
                issuer="https://auth.soopa.local",
                client_id=platform_client_id,
            ),
        ),
        fallback=GlobalHomeRealmResolver(
            global_realm="soopa-global",
            issuer="https://auth.soopa.local",
            client_id="soopa-global-web",
        ),
    )


def test_verified_enterprise_domain_routes_to_dedicated_realm_with_sso() -> None:
    catalog = InMemoryGlobalAuthzCatalog(
        email_domain_routes=(
            EmailDomainRouteDTO(
                domain="acme.com",
                tenant_id="tenant-acme",
                idp_issuer="https://sso.acme.com",
                idp_realm_name="acme-prod",
                sso_enforced=True,
                verified_at=datetime(2026, 1, 15, tzinfo=UTC),
            ),
        )
    )
    use_case = _build_use_case(catalog=catalog)

    decision = use_case.execute(ResolveHomeRealmCommand(email="  Alice@ACME.COM  "))

    assert decision == HomeRealmDecisionDTO(
        realm="acme-prod",
        issuer="https://sso.acme.com",
        client_id="client-acme-prod",
        require_sso=True,
        sso_provider=None,
        tenant_id="tenant-acme",
        login_hint="alice@acme.com",
    )


def test_unverified_enterprise_domain_cannot_hijack_login_and_falls_back_to_global() -> None:
    """Security invariant: unverified domain claims must never divert users to a tenant realm."""
    catalog = InMemoryGlobalAuthzCatalog(
        email_domain_routes=(
            EmailDomainRouteDTO(
                domain="unverified.example",
                tenant_id="tenant-untrusted",
                idp_issuer="https://evil.example",
                idp_realm_name="hijacked-realm",
                sso_enforced=True,
                verified_at=None,
            ),
        )
    )
    use_case = _build_use_case(catalog=catalog)

    decision = use_case.execute(ResolveHomeRealmCommand(email="victim@unverified.example"))

    assert decision.realm == "soopa-global"
    assert decision.issuer == "https://auth.soopa.local"
    assert decision.client_id == "soopa-global-web"
    assert decision.require_sso is False
    assert decision.tenant_id is None


def test_verified_enterprise_route_uses_default_issuer_when_idp_issuer_blank() -> None:
    catalog = InMemoryGlobalAuthzCatalog(
        email_domain_routes=(
            EmailDomainRouteDTO(
                domain="subsidiary.io",
                tenant_id="tenant-sub",
                idp_issuer="",
                idp_realm_name="sub-realm",
                sso_enforced=False,
                verified_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )
    )
    use_case = _build_use_case(catalog=catalog)

    decision = use_case.execute(ResolveHomeRealmCommand(email="ops@subsidiary.io"))

    assert decision.realm == "sub-realm"
    assert decision.issuer == "https://auth.soopa.local"
    assert decision.client_id == "client-sub-realm"
    assert decision.require_sso is False


def test_platform_operator_domain_routes_to_isolated_platform_realm() -> None:
    use_case = _build_use_case(
        catalog=InMemoryGlobalAuthzCatalog(),
        platform_domains=frozenset({"  Soopa.IO ", ""}),
        platform_client_id="soopa-admin-client",
    )

    decision = use_case.execute(ResolveHomeRealmCommand(email="SRE@SOOPA.IO"))

    assert decision == HomeRealmDecisionDTO(
        realm="soopa-platform",
        issuer="https://auth.soopa.local",
        client_id="soopa-admin-client",
        require_sso=False,
        sso_provider=None,
        tenant_id=None,
        login_hint="sre@soopa.io",
    )


def test_platform_resolver_skips_when_platform_client_id_unconfigured() -> None:
    use_case = _build_use_case(
        catalog=None,
        platform_domains=frozenset({"soopa.io"}),
        platform_client_id="",
    )

    decision = use_case.execute(ResolveHomeRealmCommand(email="ops@soopa.io"))

    assert decision.realm == "soopa-global"
    assert decision.client_id == "soopa-global-web"


def test_unknown_or_malformed_email_falls_back_to_global_without_leaking_tenant() -> None:
    """Anti-enumeration invariant: unknown and malformed inputs return uniform global fallback."""
    use_case = _build_use_case(catalog=InMemoryGlobalAuthzCatalog())

    unknown = use_case.execute(ResolveHomeRealmCommand(email="nobody@unknown-corp.example"))
    malformed = use_case.execute(ResolveHomeRealmCommand(email="   not-an-email   "))
    empty = use_case.execute(ResolveHomeRealmCommand(email="   "))

    assert unknown.realm == "soopa-global"
    assert unknown.tenant_id is None
    assert unknown.login_hint == "nobody@unknown-corp.example"

    assert malformed.realm == "soopa-global"
    assert malformed.tenant_id is None
    assert malformed.login_hint == "not-an-email"

    assert empty.realm == "soopa-global"
    assert empty.login_hint is None


def test_custom_resolver_plugs_into_chain_without_modifying_use_case() -> None:
    use_case = ResolveHomeRealmUseCase(
        resolvers=(_PartnerWhiteLabelResolver(),),
        fallback=GlobalHomeRealmResolver(
            global_realm="soopa-global",
            issuer="https://auth.soopa.local",
            client_id="soopa-global-web",
        ),
    )

    decision = use_case.execute(ResolveHomeRealmCommand(email="user@partner.example"))

    assert decision.realm == "partner-eu"
    assert decision.sso_provider == "okta"
    assert decision.require_sso is True
    assert decision.tenant_id == "tenant-partner-1"
