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

from typing import Any

import structlog
from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, Path, Request, status
from identity.domain.identity_context import IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.bootstrap.container import Container
from ucp.bootstrap.dependencies import get_db_session
from ucp.ports.outbound.tenant_repository import ITenantRepository

logger = structlog.get_logger(__name__)


@inject
async def require_tenant_member(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Any = Depends(Provide[Container.tenant_repo.provider]),
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
    identity: IdentityContext | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TENANT_GUARD_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant_repo: ITenantRepository = tenant_repo_factory(session=session)

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
    if tenant_id in identity.authorized_tenants or identity.tenant_id == tenant_id:
        request.state.identity = identity
        request.state.ucp_tenant_id = tenant_id
        return identity

    # If the user reaches this point, they do not have the requested tenant in their context.
    # The middleware is responsible for mapping IdP IDs to Canonical IDs.
    logger.debug(
        "Tenant authorization failed. requested=%s context_tenant=%s authorized_tenants=%s",
        tenant_id,
        identity.tenant_id,
        identity.authorized_tenants,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"User does not belong to tenant {tenant_id}.",
    )
