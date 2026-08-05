"""
Platform Auth Guard — FastAPI Dependency.

Validates the incoming Bearer token and enforces that the authenticated identity
holds platform-administrator privileges (i.e., the canonical sentinel tenant ID
``ten_000000000000000000000000`` is present in their authorized_tenants set).

Architecture note:
  This is a pure Inbound Adapter in the Hexagonal sense. It sits at the HTTP
  boundary, translates JWT auth into domain ``IdentityContext``, and raises
  FastAPI HTTPExceptions. It must NOT leak into the Application or Domain layers.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from identity.adapters.outbound.zitadel.jwks_token_verifier import ZitadelTokenVerifier
from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import IdentityContext

from ucp_api.core.container import get_token_verifier

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    token_verifier: Annotated[ZitadelTokenVerifier, Depends(get_token_verifier)],
) -> IdentityContext:
    """
    Inner dependency: extracts and verifies the Bearer token, returning a fully
    populated IdentityContext. Raises 401 if the token is absent or invalid.
    """
    authorization = f"Bearer {credentials.credentials}" if credentials else None
    try:
        return await authenticate_bearer_token(authorization, token_verifier)
    except AuthenticationError as exc:
        logger.warning("Authentication failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during token verification")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def require_platform_admin(
    identity: Annotated[IdentityContext, Depends(_resolve_identity)],
    request: Request,
) -> IdentityContext:
    """
    FastAPI dependency that enforces Platform Administrator privileges.

    On success, attaches the ``IdentityContext`` to ``request.state.identity``
    so downstream handlers and proxy controllers can consume it without
    re-authenticating.

    Raises:
        HTTP 401 — if the Bearer token is missing or invalid.
        HTTP 403 — if the token is valid but the user is not a platform admin.
    """
    if not identity.is_platform_admin:
        logger.warning(
            "Platform access denied for subject=%s (not a platform admin)", identity.subject
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform Administrator privileges required.",
        )

    request.state.identity = identity
    return identity
