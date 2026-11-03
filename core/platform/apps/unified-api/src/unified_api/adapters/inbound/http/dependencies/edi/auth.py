import structlog
from edi.application.use_cases.authorization.get_authorization_profile_use_case import (
    GetAuthorizationProfileQuery,
    GetAuthorizationProfileUseCase,
)
from edi.ports.outbound.tenant_repository import TenantRepositoryPort
from fastapi import Depends, HTTPException, Request, status
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from seedwork.domain.types import JsonDict

from unified_api.adapters.inbound.http.dependencies.edi.services import get_tenant_repo

logger = structlog.get_logger(__name__)


def _extract_role_names(token_payload: JsonDict) -> tuple[str, ...]:
    """Normalize role claims from either list or mapping token shapes."""
    raw_roles = token_payload.get("roles")
    if isinstance(raw_roles, dict):
        return tuple(str(key) for key in raw_roles)
    if isinstance(raw_roles, list):
        return tuple(str(item) for item in raw_roles)
    return ()


async def get_identity_context(
    request: Request,
) -> IdentityContext:
    """Extract the authenticated identity from the request or raise HTTP 401."""
    logger.debug(
        "edi_guard_executing",
        request_url_path=request.url.path,
    )

    identity: IdentityContext | None = request.state.identity
    if identity is not None:
        logger.debug(
            "edi_guard_identity_found_in_state",
            identity_subject=identity.subject,
        )

    if identity is None:
        logger.debug("edi_guard_identity_checking_scope")
        scoped_identity = request.scope.get("identity")
        if isinstance(scoped_identity, IdentityContext):
            identity = scoped_identity
            logger.debug(
                "edi_guard_identity_found_in_scope",
                identity_subject=identity.subject,
            )

    if identity is None:
        logger.error("edi_guard_identity_context_missing", request_url_path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="IDENTITY_CONTEXT_MISSING",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


async def get_raw_jwt(
    identity: IdentityContext = Depends(get_identity_context),
) -> JsonDict:
    """Compatibility layer for routes inspecting structured token claims."""
    return identity.claims


async def get_current_tenant_id(
    request: Request,
) -> str:
    """Return the active tenant ID enforced by TenantContextMiddleware."""
    tenant_id = request.state.tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Perimeter failed to inject tenant_id into request state.",
        )
    return str(tenant_id)


def require_platform_admin(identity: IdentityContext = Depends(get_identity_context)) -> str:
    """Enforce that the caller holds Platform Admin privileges."""
    is_platform_admin = (
        "PlatformAdmin" in identity.roles or PLATFORM_TENANT_ID in identity.authorized_tenants
    )
    if not is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden. This action requires Platform Admin privileges.",
        )
    return PLATFORM_TENANT_ID


def get_authorization_use_case(
    tenant_repo: TenantRepositoryPort = Depends(get_tenant_repo),
) -> GetAuthorizationProfileUseCase:
    return GetAuthorizationProfileUseCase(tenant_repo)


async def get_current_user_profile(
    tenant_id: str = Depends(get_current_tenant_id),
    token_payload: JsonDict = Depends(get_raw_jwt),
    auth_use_case: GetAuthorizationProfileUseCase = Depends(get_authorization_use_case),
) -> JsonDict:
    roles = _extract_role_names(token_payload)
    is_platform_admin = tenant_id == PLATFORM_TENANT_ID or "PlatformAdmin" in roles
    profile = await auth_use_case.execute(
        GetAuthorizationProfileQuery(
            tenant_id=tenant_id,
            is_platform_admin=is_platform_admin,
            current_rls_tenant=None,
            roles=roles,
        )
    )
    return profile.to_dict()


async def get_platform_user_profile(
    _platform_tenant_id: str = Depends(require_platform_admin),
    token_payload: JsonDict = Depends(get_raw_jwt),
    auth_use_case: GetAuthorizationProfileUseCase = Depends(get_authorization_use_case),
) -> JsonDict:
    """Dedicated dependency for Platform Admin routes bound strictly to PLATFORM_TENANT_ID."""
    roles = _extract_role_names(token_payload)
    profile = await auth_use_case.execute(
        GetAuthorizationProfileQuery(
            tenant_id=PLATFORM_TENANT_ID,
            is_platform_admin=True,
            current_rls_tenant=None,
            roles=roles,
        )
    )
    return profile.to_dict()
