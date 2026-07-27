import logging
from typing import Any

from config.settings import get_settings
from fastapi import Depends, Header, HTTPException, Request, status
from identity.adapters.outbound.zitadel.jwks_token_verifier import (
    ZitadelTokenVerifier,
    ZitadelTokenVerifierOptions,
)
from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import IdentityContext

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

async def get_current_tenant_id(
    request: Request,
    identity: IdentityContext = Depends(get_identity_context),
) -> str:
    """Extracts tenant ID dynamically from the URL and enforces Zero Trust ACL."""
    tenant_id = request.path_params.get("tenant_id")
    is_platform_admin = "PlatformAdmin" in identity.roles or "0" in identity.authorized_tenants

    logger.info(f"get_current_tenant_id: tenant_id={tenant_id}, roles={identity.roles}, authorized_tenants={identity.authorized_tenants}, is_platform_admin={is_platform_admin}")

    if not tenant_id:
        if is_platform_admin:
            logger.info("get_current_tenant_id: No tenant_id in path, but user is platform admin. Returning '0'.")
            return "0"
        logger.warning(f"get_current_tenant_id: Raising 400 Bad Request because tenant_id is missing and user is not platform admin. Roles: {identity.roles}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant ID missing from request path.",
        )

    if tenant_id not in identity.authorized_tenants and not is_platform_admin:
        logger.warning(f"get_current_tenant_id: Raising 403 Forbidden because {tenant_id} is not in {identity.authorized_tenants} and user is not platform admin.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token does not grant cryptographic roles for tenant {tenant_id}.",
        )
    return tenant_id


def require_platform_admin(identity: IdentityContext = Depends(get_identity_context)) -> str:
    """
    Dependency that enforces the user has Platform Admin privileges.
    """
    is_platform_admin = "PlatformAdmin" in identity.roles or "0" in identity.authorized_tenants
    if not is_platform_admin:
        raise HTTPException(
            status_code=403,
            detail="Forbidden. This action requires Platform Admin privileges.",
        )
    return "0"


def get_authorization_service(
    tenant_repo: TenantRepositoryPort = Depends(get_tenant_repo),
) -> AuthorizationService:
    return AuthorizationService(tenant_repo)


async def get_current_user_profile(
    tenant_id: str = Depends(get_current_tenant_id),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    auth_service: AuthorizationService = Depends(get_authorization_service),
) -> dict[str, Any]:
    if not tenant_id.isdigit():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid tenant ID format. Expected numeric tenant identifier.",
        )

    roles = token_payload.get("roles", [])
    if isinstance(roles, dict):
        roles = list(roles.keys())

    is_platform_admin = tenant_id == "0" or "PlatformAdmin" in roles

    return await auth_service.get_authorization_profile(
        tenant_id=tenant_id,
        is_platform_admin=is_platform_admin,
        current_rls_tenant=None,
        roles=roles,
    )
