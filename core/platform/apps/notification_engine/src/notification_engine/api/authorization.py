from fastapi import HTTPException, Request, status


def assert_tenant_authorized(request: Request, tenant_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity is not authorized to access
    the requested tenant. Guards all tenant-scoped endpoints against IDOR.
    """
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    authorized: set[str] = getattr(identity, "authorized_tenants", set()) or set()
    if tenant_id not in authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this tenant's resources",
        )


def assert_user_matches_identity(request: Request, user_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity does not match the requested user_id.
    """
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if getattr(identity, "user_id", None) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this user's data.",
        )
