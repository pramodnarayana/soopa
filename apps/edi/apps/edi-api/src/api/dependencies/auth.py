import logging
import time
from typing import Any

from config.settings import get_settings
from fastapi import Depends, Header, HTTPException, Request, status
from identity.adapters.outbound.zitadel.jwks_token_verifier import (
    ZitadelTokenVerifier,
    ZitadelTokenVerifierOptions,
)
from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext

from api.core.authorization import AuthorizationService
from api.dependencies.services import get_tenant_repo
from api.ports.tenant_repository import TenantRepositoryPort

_settings = get_settings()
token_verifier = ZitadelTokenVerifier(
    ZitadelTokenVerifierOptions(
        issuer=_settings.identity.issuer,
        audience=_settings.identity.audience,
        jwks_url=_settings.identity.jwks_url,
    )
)


async def get_identity_context(
    authorization: str | None = Header(default=None),
) -> IdentityContext:
    try:
        return await authenticate_bearer_token(authorization, token_verifier)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_raw_jwt(
    identity: IdentityContext = Depends(get_identity_context),
) -> dict[str, Any]:
    """Compatibility layer for legacy routes expecting raw token claims."""
    return identity.claims


logger = logging.getLogger(__name__)

# Simple TTL cache for UCP tenant ID -> IdP tenant ID mapping
_tenant_mapping_cache: dict[str, tuple[str, float]] = {}  # {ucp_tenant_id: (idp_tenant_id, expiry_timestamp)}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def invalidate_tenant_mapping_cache(tenant_id: str) -> None:
    """
    Invalidate a specific tenant mapping entry from the cache.
    Should be called after tenant updates or deletions to ensure consistency.
    """
    _tenant_mapping_cache.pop(tenant_id, None)


async def get_current_tenant_id(
    request: Request,
    identity: IdentityContext = Depends(get_identity_context),
    tenant_repo: TenantRepositoryPort = Depends(get_tenant_repo),
) -> str:
    # Extract tenant ID:
    # 1. Header (Internal UCP ID passed by Gateway)
    # 2. Path param (Fallback if external caller)
    tenant_id = request.headers.get("x-tenant-id") or request.path_params.get("tenant_id")

    is_platform_admin = (
        "PlatformAdmin" in identity.roles or PLATFORM_TENANT_ID in identity.authorized_tenants
    )

    if not tenant_id:
        if is_platform_admin:
            return PLATFORM_TENANT_ID
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant ID missing from request.",
        )

    # 1. Fast Path: If they passed the Zitadel ID directly and it matches
    if tenant_id in identity.authorized_tenants:
        return str(tenant_id)

    # 2. Translate internal UCP ID (`ten_...`) to verify against JWT (Zitadel ID)
    # Check cache first
    current_time = time.time()
    cached_entry = _tenant_mapping_cache.get(tenant_id)
    if cached_entry:
        idp_tenant_id, expiry = cached_entry
        if current_time < expiry and idp_tenant_id in identity.authorized_tenants:
            return str(tenant_id)

    # Cache miss or expired, fetch from repository
    tenant_record = await tenant_repo.get_tenant(tenant_id)
    if tenant_record and tenant_record.get("idp_tenant_id"):
        # Update cache
        idp_tenant_id = tenant_record["idp_tenant_id"]
        _tenant_mapping_cache[tenant_id] = (idp_tenant_id, current_time + _CACHE_TTL_SECONDS)

        if idp_tenant_id in identity.authorized_tenants:
            return str(tenant_id)

    if not is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token does not grant access to tenant {tenant_id}.",
        )

    return str(tenant_id)


def require_platform_admin(identity: IdentityContext = Depends(get_identity_context)) -> str:
    """
    Dependency that enforces the user has Platform Admin privileges.
    """
    is_platform_admin = (
        "PlatformAdmin" in identity.roles or PLATFORM_TENANT_ID in identity.authorized_tenants
    )
    if not is_platform_admin:
        raise HTTPException(
            status_code=403,
            detail="Forbidden. This action requires Platform Admin privileges.",
        )
    return PLATFORM_TENANT_ID


def get_authorization_service(
    tenant_repo: TenantRepositoryPort = Depends(get_tenant_repo),
) -> AuthorizationService:
    return AuthorizationService(tenant_repo)


async def get_current_user_profile(
    tenant_id: str = Depends(get_current_tenant_id),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    auth_service: AuthorizationService = Depends(get_authorization_service),
) -> dict[str, Any]:
    # UCP Tenant IDs are strings like `ten_...` so we no longer check .isdigit()
    roles = token_payload.get("roles", [])
    if isinstance(roles, dict):
        roles = list(roles.keys())

    is_platform_admin = tenant_id == PLATFORM_TENANT_ID or "PlatformAdmin" in roles

    return await auth_service.get_authorization_profile(
        tenant_id=tenant_id,
        is_platform_admin=is_platform_admin,
        current_rls_tenant=None,
        roles=roles,
    )
