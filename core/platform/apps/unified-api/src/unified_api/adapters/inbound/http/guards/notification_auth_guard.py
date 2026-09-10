import structlog
from fastapi import HTTPException, Request, status

logger = structlog.get_logger(__name__)


def assert_tenant_authorized(request: Request, tenant_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity is not authorized to access
    the requested tenant. Guards all tenant-scoped endpoints against IDOR.
    """
    identity = request.state.identity
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    authorized: set[str] = identity.authorized_tenants
    if tenant_id not in authorized:
        logger.warning(
            "authz.denied.tenant_idor",
            path=request.url.path,
            requested_tenant=tenant_id,
            subject=identity.subject,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tenant's resources",
        )


def assert_user_matches_identity(request: Request, user_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity does not match the requested user_id.
    """
    identity = request.state.identity
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if identity.subject != user_id:
        logger.warning(
            "authz.denied.user_idor",
            path=request.url.path,
            requested_user=user_id,
            subject=identity.subject,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this user's data.",
        )
