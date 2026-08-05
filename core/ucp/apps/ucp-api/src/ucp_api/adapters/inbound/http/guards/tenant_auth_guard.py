"""
Tenant Auth Guard — FastAPI Dependency.

Validates the incoming Bearer token, then enforces that the authenticated identity
is authorized to act on the requested tenant. Supports two cases:

  1. Platform Admins — can access any tenant unconditionally.
  2. Standard tenant users — must strictly belong to the requested tenant. If
     the request path param is an IdP Org ID (not a canonical UCP tenant ID),
     the guard resolves it via the repository and compares against the canonical ID.

The resolved canonical UCP tenant ID is attached to ``request.state.ucp_tenant_id``
so downstream handlers (e.g. the tenant-proxy controller) can consume it without
re-querying the database.

Architecture note:
  This is a pure Inbound Adapter. It translates HTTP concepts (path params,
  JWT headers) into domain intent using the ITenantRepository port. It must
  NOT be imported or used from the Application or Domain layers.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from identity.adapters.outbound.zitadel.jwks_token_verifier import ZitadelTokenVerifier
from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import IdentityContext

from ucp_api.core.container import get_token_verifier
from ucp_api.ports.outbound.tenant_repository import ITenantRepository

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    token_verifier: Annotated[ZitadelTokenVerifier, Depends(get_token_verifier)],
) -> IdentityContext:
    """Extracts and verifies the Bearer token. Raises 401 on failure."""
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


# Dependency injection placeholder — overridden in main.py
def get_tenant_repo_for_guard() -> ITenantRepository:
    raise NotImplementedError()


async def require_tenant_member(
    request: Request,
    identity: Annotated[IdentityContext, Depends(_resolve_identity)],
    tenant_repo: Annotated[ITenantRepository, Depends(get_tenant_repo_for_guard)],
    # Path param name matches the route definition: /tenants/{tenant_id}/...
    tenant_id: str = Path(...),
) -> IdentityContext:
    """
    FastAPI dependency that enforces tenant membership.

    On success:
      - Attaches ``IdentityContext`` to ``request.state.identity``.
      - Attaches the resolved canonical UCP tenant ID to ``request.state.ucp_tenant_id``.
        This is important because the path param may be an IdP Org ID, and downstream
        code (e.g. the proxy controller) needs the canonical ``ten_...`` ID.

    Raises:
        HTTP 401 — if the Bearer token is missing or invalid.
        HTTP 403 — if the user is not authorized to access the requested tenant,
                   or if the tenant cannot be resolved at all.
    """
    # Platform Admins bypass all tenant-level ACL checks.
    # But we still need to normalize the tenant_id if it's an IdP Org ID.
    if identity.is_platform_admin:
        # Try to resolve as IdP tenant ID first to get canonical UCP ID
        resolved = await tenant_repo.find_by_idp_tenant_id(tenant_id)
        canonical_tenant_id = resolved.id if resolved else tenant_id

        request.state.identity = identity
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    # Standard users: the token must carry the correct tenant context.
    if identity.tenant_id == tenant_id:
        request.state.identity = identity
        request.state.ucp_tenant_id = tenant_id
        return identity

    # Fallback: the path param might be a Zitadel Org ID rather than our canonical ID.
    # Resolve it via the repository and re-check.
    logger.debug(
        "Tenant ID mismatch — attempting IdP resolution. requested=%s context=%s",
        tenant_id,
        identity.tenant_id,
    )
    resolved = await tenant_repo.find_by_idp_tenant_id(tenant_id)

    if resolved is None:
        logger.debug("IdP resolution failed — no tenant found for idpTenantId=%s", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User does not belong to tenant {tenant_id}.",
        )

    if identity.tenant_id != resolved.id:
        logger.debug(
            "IdP resolution succeeded but canonical ID mismatch. context=%s resolved=%s",
            identity.tenant_id,
            resolved.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User does not belong to tenant {tenant_id}.",
        )

    # Resolved via IdP Org ID — update the canonical ID on the request state.
    request.state.identity = identity
    request.state.ucp_tenant_id = resolved.id
    return identity
