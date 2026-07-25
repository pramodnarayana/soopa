from typing import Any

from config.settings import get_settings
from fastapi import Depends, Header, HTTPException, status
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


async def get_current_tenant_id(
    identity: IdentityContext = Depends(get_identity_context),
) -> str:
    """Extracts tenant ID dynamically from the validated JWT."""
    try:
        return str(identity.tenant_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not contain a valid urn:zitadel:iam:org:id claim for tenant isolation.",
        ) from exc


def require_platform_admin(tenant_id: str = Depends(get_current_tenant_id)) -> str:
    """
    Dependency that enforces the user belongs to Tenant 0 (Platform Admin).
    """
    if tenant_id != "0":
        raise HTTPException(
            status_code=403,
            detail="Forbidden. This action requires Platform Admin (Tenant 0) privileges.",
        )
    return tenant_id


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

    is_platform_admin = tenant_id == "0" or "Platform_Admin" in roles

    return await auth_service.get_authorization_profile(
        tenant_id=int(tenant_id),
        is_platform_admin=is_platform_admin,
        current_rls_tenant=None,
        roles=roles,
    )

