"""
Platform Auth Guard — FastAPI Dependency.

Enforces Platform Administrator privileges through the 4-Layer Local PDP
(`RequireCapability(Capability.PLATFORM_ADMIN, app_slug=CoreControlPlaneAppSlug.PLATFORM)`),
preserving structured error logging and fail-closed semantics.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Request, status
from identity.domain.authorization import Capability
from identity.domain.constants import CoreControlPlaneAppSlug
from identity.domain.identity_context import IdentityContext

from unified_api.adapters.inbound.http.guards.request_context import (
    resolve_identity,
    resolve_runtime_and_db,
)
from unified_api.adapters.inbound.http.guards.require_capability_guard import RequireCapability

logger = structlog.get_logger(__name__)

_PLATFORM_ADMIN_GUARD = RequireCapability(
    Capability.PLATFORM_ADMIN,
    app_slug=CoreControlPlaneAppSlug.PLATFORM.value,
)


async def require_platform_admin(
    request: Request,
) -> IdentityContext:
    """
    FastAPI dependency enforcing Platform Administrator privileges.

    Delegates fail-closed to the 4-Layer Local PDP whenever `identity_authz` is
    attached to `app.state`, and enforces strict `IdentityContext.is_platform_admin`
    with structured `logger.error` audit logs in standalone unit-test contexts.
    """
    identity = resolve_identity(request)
    if identity is None:
        logger.error("authz.denied.platform_unauthenticated", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PLATFORM_GUARD_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    authz_runtime, _ = resolve_runtime_and_db(request)
    if authz_runtime is not None:
        return await _PLATFORM_ADMIN_GUARD(request)

    if not identity.is_platform_admin:
        logger.error(
            "authz.denied.platform_admin_required",
            path=request.url.path,
            subject=identity.subject,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Administrator privileges required.",
        )

    return identity
