"""Notification Inbound HTTP IDOR Authorization Guards."""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Request, status

from unified_api.adapters.inbound.http.guards.request_context import resolve_identity

logger = structlog.get_logger(__name__)


def assert_tenant_authorized(request: Request, tenant_id: str) -> None:
    """
    Raises HTTP 403 if the authenticated identity is not authorized to access
    the requested tenant. Guards all tenant-scoped endpoints against IDOR.
    """
    identity = resolve_identity(request)
    if identity is None:
        logger.error("authz.denied.unauthenticated", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    authorized: set[str] = identity.authorized_tenants
    if tenant_id not in authorized:
        logger.error(
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
    identity = resolve_identity(request)
    if identity is None:
        logger.error("authz.denied.unauthenticated", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if identity.subject != user_id:
        logger.error(
            "authz.denied.user_idor",
            path=request.url.path,
            requested_user=user_id,
            subject=identity.subject,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this user's data.",
        )
