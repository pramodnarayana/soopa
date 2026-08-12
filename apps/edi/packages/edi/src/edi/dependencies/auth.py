import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext

from edi.core.authorization import AuthorizationService
from edi.dependencies.services import get_tenant_repo
from edi.ports.tenant_repository import TenantRepositoryPort


async def get_identity_context(
    request: Request,
) -> IdentityContext:
    """
    Extracts the authenticated identity from the request.
    Throws a 401 if the user is unauthenticated.
    """
    logger = logging.getLogger(__name__)

    logger.info(f"[EDI_GUARD] get_identity_context executing for {request.url.path}")

    identity: IdentityContext | None = getattr(request.state, "identity", None)
    if identity is not None:
        logger.info(f"[EDI_GUARD] Found identity in request.state: {identity.subject}")

    if identity is None:
        logger.warning("[EDI_GUARD] Identity NOT found in request.state. Checking scope...")
        identity = request.scope.get("identity")
        if identity is not None:
            logger.info(f"[EDI_GUARD] Found identity in request.scope: {identity.subject}")
        else:
            logger.warning("[EDI_GUARD] Identity NOT found in request.scope either!")

    if identity is None:
        logger.error("[EDI_GUARD] FAILED. Returning 401 IDENTITY_CONTEXT_MISSING")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="IDENTITY_CONTEXT_MISSING",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


async def get_raw_jwt(
    identity: IdentityContext = Depends(get_identity_context),
) -> dict[str, Any]:
    """Compatibility layer for legacy routes expecting raw token claims."""
    return identity.claims


logger = logging.getLogger(__name__)


async def get_current_tenant_id(
    request: Request,
) -> str:
    """
    Dependency to get the active Tenant ID.
    The TenantContextMiddleware in the Unified API Shell enforces this before routing.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Perimeter failed to inject tenant_id into request state.",
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


async def get_platform_user_profile(
    tenant_id: str = Depends(require_platform_admin),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    auth_service: AuthorizationService = Depends(get_authorization_service),
) -> dict[str, Any]:
    """
    Dedicated dependency for Platform Admin routes.
    It explicitly uses the trusted PLATFORM_TENANT_ID and bypasses any client-provided headers.
    """
    roles = token_payload.get("roles", [])
    if isinstance(roles, dict):
        roles = list(roles.keys())

    return await auth_service.get_authorization_profile(
        tenant_id=PLATFORM_TENANT_ID,
        is_platform_admin=True,
        current_rls_tenant=None,
        roles=roles,
    )
