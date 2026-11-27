"""Authentication & Home Realm Discovery (HRD) HTTP Router."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from identity.application.resolve_home_realm_use_case import ResolveHomeRealmCommand
from identity.domain.constants import MFA_AMR_VALUES
from identity.domain.identity_context import IdentityContext
from pydantic import BaseModel, Field

from unified_api.bootstrap.identity_authz import IdentityAuthzRuntime

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_EMAIL_REGEX = r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$"


class AuthMeResponse(BaseModel):
    authenticated: bool
    subject: str | None = None
    email: str | None = None
    name: str | None = None
    tenantId: str | None = None
    idpRealm: str | None = None
    isPlatformAdmin: bool | None = None
    mfaVerified: bool | None = None
    capabilities: list[str] | None = None
    authorizedTenants: list[str] | None = None
    subscribedApps: list[str] | None = None


class HrdRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=_EMAIL_REGEX)


class HrdResponse(BaseModel):
    """Minimal public HRD response required for OAuth 2.1 redirect (zero internal tenant IDs)."""

    realm: str
    issuer: str
    clientId: str
    requireSso: bool
    ssoProvider: str | None = None
    loginHint: str | None = None


def _extract_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


@router.post("/hrd", response_model=HrdResponse)
async def home_realm_discovery(payload: HrdRequest, request: Request) -> HrdResponse:
    """Public Home Realm Discovery (HRD) HTTP adapter delegating to Composition Root Use Case."""
    try:
        authz_runtime: IdentityAuthzRuntime | None = request.app.state.identity_authz
    except AttributeError:
        authz_runtime = None

    if authz_runtime is None:
        logger.error("auth_hrd_runtime_uninitialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity discovery service is unavailable.",
        )

    client_ip = _extract_client_ip(request)
    allowed, retry_after = authz_runtime.hrd_rate_limiter.check_and_record(client_ip)
    if not allowed:
        logger.error("auth_hrd_rate_limited", client_ip=client_ip, retry_after=retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in discovery requests. Please wait and try again.",
            headers={"Retry-After": str(retry_after)},
        )

    decision = authz_runtime.home_realm_use_case.execute(
        ResolveHomeRealmCommand(email=payload.email)
    )
    return HrdResponse(
        realm=decision.realm,
        issuer=decision.issuer,
        clientId=decision.client_id,
        requireSso=decision.require_sso,
        ssoProvider=decision.sso_provider,
        loginHint=decision.login_hint,
    )


@router.get("/me", response_model=AuthMeResponse)
async def get_me(request: Request) -> AuthMeResponse:
    """Return the authenticated user's IdP-agnostic IdentityContext, capabilities, and subscribed apps."""
    try:
        identity: IdentityContext | None = request.state.identity
    except AttributeError:
        identity = None
    if not identity:
        return AuthMeResponse(authenticated=False)

    active_tenant_id = request.headers.get("x-tenant-id") or identity.tenant_id
    subscribed_apps: list[str] = []
    try:
        db_provider = request.app.state.db_provider
        authz_runtime = request.app.state.identity_authz
    except AttributeError:
        db_provider = None
        authz_runtime = None

    if active_tenant_id and db_provider is not None and authz_runtime is not None:
        async with db_provider.session() as session:
            entitlements = authz_runtime.build_entitlements(session)
            apps = await entitlements.get_enabled_app_slugs(tenant_id=active_tenant_id)
            subscribed_apps = sorted(apps)

    raw_amr = identity.claims.get("amr")
    amr_values = (
        {str(item).lower() for item in raw_amr}
        if isinstance(raw_amr, (list, tuple, set))
        else set()
    )
    mfa_verified = bool(amr_values & MFA_AMR_VALUES)

    raw_realm = identity.claims.get("owner") or identity.claims.get("idp_realm")
    idp_realm = str(raw_realm) if isinstance(raw_realm, str) and raw_realm else None

    return AuthMeResponse(
        authenticated=True,
        subject=identity.subject,
        email=str(identity.claims.get("email")) if identity.claims.get("email") else None,
        name=str(identity.claims.get("name")) if identity.claims.get("name") else None,
        tenantId=active_tenant_id,
        idpRealm=idp_realm,
        isPlatformAdmin=identity.is_platform_admin,
        mfaVerified=mfa_verified,
        capabilities=sorted(list(identity.capabilities)),
        authorizedTenants=sorted(list(identity.authorized_tenants)),
        subscribedApps=subscribed_apps,
    )
