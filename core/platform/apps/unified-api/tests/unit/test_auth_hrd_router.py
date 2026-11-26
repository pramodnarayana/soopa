"""Unit tests for Home Realm Discovery (POST /api/v1/auth/hrd)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.application.resolve_home_realm_use_case import (
    GlobalHomeRealmResolver,
    ResolveHomeRealmCommand,
    ResolveHomeRealmUseCase,
)
from identity.config import PlatformIdentitySettings
from identity.domain.dtos import EmailDomainRouteDTO, HomeRealmDecisionDTO
from identity.domain.identity_context import (
    PLATFORM_ADMIN_CAPABILITY,
    PLATFORM_TENANT_ID,
    IdentityContext,
)

from unified_api.adapters.inbound.http.identity.routers.auth_router import router as auth_router
from unified_api.bootstrap.identity_authz import (
    SlidingWindowRateLimiter,
    build_home_realm_use_case,
)


@dataclass(frozen=True)
class _StubAuthzRuntime:
    global_catalog: InMemoryGlobalAuthzCatalog
    home_realm_use_case: ResolveHomeRealmUseCase
    hrd_rate_limiter: SlidingWindowRateLimiter


def _build_test_app(*, max_requests: int = 30) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")

    identity_settings = PlatformIdentitySettings(
        _env_file=None,
        IDENTITY_ISSUER="http://localhost:8080",
        IDENTITY_PLATFORM_REALM="soopa-platform",
        IDENTITY_GLOBAL_REALM="soopa-global",
        IDENTITY_OAUTH_CLIENT_ID="soopa_dashboard_cid",
        IDENTITY_PLATFORM_ADMIN_CLIENT_ID="soopa_platform_admin_cid",
        IDENTITY_PLATFORM_ADMIN_DOMAINS="flowwolf.io",
        IDENTITY_SHARED_APP_REALM_DELIMITER="-org-",
    )
    catalog = InMemoryGlobalAuthzCatalog()
    catalog.upsert_email_domain_route(
        EmailDomainRouteDTO(
            domain="enterprise.example",
            tenant_id="tnt_demo_enterprise",
            idp_realm_name="org_demo_enterprise",
            idp_issuer="http://localhost:8080",
            sso_enforced=True,
            verified_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    catalog.upsert_email_domain_route(
        EmailDomainRouteDTO(
            domain="unverified.example",
            tenant_id="tnt_unverified",
            idp_realm_name="org_unverified",
            idp_issuer="https://evil.example",
            sso_enforced=True,
            verified_at=None,
        )
    )

    home_realm_use_case = build_home_realm_use_case(
        settings=identity_settings,
        global_catalog=catalog,
    )
    app.state.identity_authz = _StubAuthzRuntime(
        global_catalog=catalog,
        home_realm_use_case=home_realm_use_case,
        hrd_rate_limiter=SlidingWindowRateLimiter(max_requests=max_requests, window_seconds=60.0),
    )
    return TestClient(app)


def test_hrd_routes_verified_enterprise_domain_without_exposing_tenant_id() -> None:
    client = _build_test_app()
    resp = client.post("/api/v1/auth/hrd", json={"email": "Alice@Enterprise.Example"})
    assert resp.status_code == 200
    body = resp.json()
    assert "tenantId" not in body
    assert body == {
        "realm": "org_demo_enterprise",
        "issuer": "http://localhost:8080",
        "clientId": "soopa_dashboard_cid-org-org_demo_enterprise",
        "requireSso": True,
        "ssoProvider": None,
        "loginHint": "alice@enterprise.example",
    }


def test_hrd_routes_platform_operator_domain_to_isolated_platform_client() -> None:
    client = _build_test_app()
    resp = client.post("/api/v1/auth/hrd", json={"email": "admin@flowwolf.io"})
    assert resp.status_code == 200
    assert resp.json() == {
        "realm": "soopa-platform",
        "issuer": "http://localhost:8080",
        "clientId": "soopa_platform_admin_cid",
        "requireSso": False,
        "ssoProvider": None,
        "loginHint": "admin@flowwolf.io",
    }


def test_hrd_falls_back_to_global_realm_for_unknown_or_personal_domains() -> None:
    client = _build_test_app()
    resp = client.post("/api/v1/auth/hrd", json={"email": "solo@gmail.com"})
    assert resp.status_code == 200
    assert resp.json() == {
        "realm": "soopa-global",
        "issuer": "http://localhost:8080",
        "clientId": "soopa_dashboard_cid-org-soopa-global",
        "requireSso": False,
        "ssoProvider": None,
        "loginHint": "solo@gmail.com",
    }


def test_hrd_ignores_unverified_enterprise_domain_route() -> None:
    client = _build_test_app()
    resp = client.post("/api/v1/auth/hrd", json={"email": "victim@unverified.example"})
    assert resp.status_code == 200
    assert resp.json() == {
        "realm": "soopa-global",
        "issuer": "http://localhost:8080",
        "clientId": "soopa_dashboard_cid-org-soopa-global",
        "requireSso": False,
        "ssoProvider": None,
        "loginHint": "victim@unverified.example",
    }


def test_hrd_rejects_malformed_email_and_enforces_rate_limit() -> None:
    client = _build_test_app(max_requests=2)

    bad = client.post("/api/v1/auth/hrd", json={"email": "not-an-email"})
    assert bad.status_code == 422

    assert client.post("/api/v1/auth/hrd", json={"email": "a@example.com"}).status_code == 200
    assert client.post("/api/v1/auth/hrd", json={"email": "b@example.com"}).status_code == 200

    limited = client.post("/api/v1/auth/hrd", json={"email": "c@example.com"})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_identity_settings_defaults_to_idp_agnostic_client_id_without_delimiter() -> None:
    settings = PlatformIdentitySettings(
        _env_file=None,
        IDENTITY_OAUTH_CLIENT_ID="generic_oidc_client",
        IDENTITY_SHARED_APP_REALM_DELIMITER="",
    )
    assert settings.resolve_realm_client_id("soopa-global") == "generic_oidc_client"


def test_resolve_home_realm_use_case_accepts_custom_ocp_resolver() -> None:
    class PartnerHomeRealmResolver:
        @property
        def name(self) -> str:
            return "partner"

        def resolve(self, *, email: str, domain: str) -> HomeRealmDecisionDTO | None:
            if domain == "partner.example":
                return HomeRealmDecisionDTO(
                    realm="partner-eu",
                    issuer="https://eu.identity.example",
                    client_id="partner_client",
                    require_sso=True,
                    login_hint=email,
                )
            return None

    use_case = ResolveHomeRealmUseCase(
        resolvers=(PartnerHomeRealmResolver(),),
        fallback=GlobalHomeRealmResolver(
            global_realm="soopa-global",
            issuer="https://identity.example",
            client_id="global_client",
        ),
    )

    partner = use_case.execute(ResolveHomeRealmCommand(email="ops@partner.example"))
    assert partner.realm == "partner-eu"
    assert partner.client_id == "partner_client"
    assert partner.require_sso is True

    fallback = use_case.execute(ResolveHomeRealmCommand(email="user@other.example"))
    assert fallback.realm == "soopa-global"
    assert fallback.client_id == "global_client"


def test_identity_context_is_platform_admin_requires_platform_tenant_membership_and_capability() -> (
    None
):
    # Both PLATFORM_TENANT_ID membership AND platform:admin capability -> True
    platform_admin = IdentityContext(
        subject="iam_usr_admin",
        claims={},
        tenant_id=PLATFORM_TENANT_ID,
        authorized_tenants={PLATFORM_TENANT_ID},
        capabilities={PLATFORM_ADMIN_CAPABILITY},
    )
    assert platform_admin.is_platform_admin is True

    # Security invariant: platform:admin capability WITHOUT PLATFORM_TENANT_ID membership -> False
    escalated_tenant_user = IdentityContext(
        subject="iam_usr_tenant",
        claims={},
        tenant_id="iam_ten_customer",
        authorized_tenants={"iam_ten_customer"},
        capabilities={PLATFORM_ADMIN_CAPABILITY},
    )
    assert escalated_tenant_user.is_platform_admin is False

    # Platform tenant membership WITHOUT platform:admin capability -> False
    unprivileged_platform_user = IdentityContext(
        subject="iam_usr_viewer",
        claims={},
        tenant_id=PLATFORM_TENANT_ID,
        authorized_tenants={PLATFORM_TENANT_ID},
        capabilities={"tenants:read"},
    )
    assert unprivileged_platform_user.is_platform_admin is False
