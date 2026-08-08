"""
Platform Auth Guard — FastAPI Dependency.

Enforces that the already-authenticated identity (resolved by the global
authentication middleware and stored on ``request.state.identity``) holds
platform-administrator privileges.

Authentication (JWT validation) is NOT repeated here — it happened exactly
once at the perimeter via ``bootstrap/middleware.py``.

Architecture note:
  This is a pure Inbound Adapter in the Hexagonal sense. It translates a
  pre-verified identity into an authorization decision. It must NOT leak
  into the Application or Domain layers.
"""

import logging

from fastapi import HTTPException, Request, status
from identity.domain.identity_context import IdentityContext

logger = logging.getLogger(__name__)


async def require_platform_admin(
    request: Request,
) -> IdentityContext:
    """
    FastAPI dependency that enforces Platform Administrator privileges.

    Reads the ``IdentityContext`` already resolved by the global authentication
    middleware. If the identity is not present (unauthenticated) or does not
    carry platform admin privileges, raises 401/403 respectively.

    Raises:
        HTTP 401 — if the request was not authenticated (no valid Bearer token).
        HTTP 403 — if the token is valid but the user is not a platform admin.
    """
    identity: IdentityContext | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PLATFORM_GUARD_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not identity.is_platform_admin:
        logger.warning(
            "Platform access denied for subject=%s (not a platform admin)", identity.subject
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Administrator privileges required.",
        )

    return identity
