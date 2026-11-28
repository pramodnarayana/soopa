"""
Tenant Auth Guard — FastAPI Dependency.

Enforces that the authenticated identity is authorized to act on the requested
tenant (direct membership, Platform Admin scope, or L1-cached `ltree` subtree
inheritance). Never mutates `IdentityContext.capabilities` in-place and avoids
unnecessary per-request database waterfalls.

The resolved canonical UCP tenant ID is attached to ``request.state.ucp_tenant_id``
so downstream handlers can consume it without re-querying the database.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, Path, Request, status
from identity.domain.constants import CANONICAL_TENANT_ID_PREFIXES
from identity.domain.identity_context import IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.bootstrap.container import Container
from ucp.bootstrap.dependencies import get_db_session
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort

from unified_api.adapters.inbound.http.guards.request_context import (
    resolve_identity,
    resolve_runtime_and_db,
)

logger = structlog.get_logger(__name__)


async def _resolve_canonical_tenant_id(
    *,
    tenant_id: str,
    identity: IdentityContext,
    session: AsyncSession,
    tenant_repo_factory: Callable[[AsyncSession], TenantRepositoryPort],
) -> str:
    """Resolve `tenant_id` to canonical `ten_...` ID with 0 DB hits for already-canonical IDs."""
    mapped = identity.tenant_mapping.get(tenant_id)
    if mapped:
        return str(mapped)
    if tenant_id.startswith(CANONICAL_TENANT_ID_PREFIXES):
        return tenant_id
    tenant_repo = tenant_repo_factory(session)
    resolved = await tenant_repo.find_by_idp_realm(tenant_id)
    return resolved.id if resolved is not None else tenant_id


@inject
async def require_tenant_member(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Callable[[AsyncSession], TenantRepositoryPort] = Depends(
        Provide[Container.tenant_repo.provider]
    ),
    # Path param name matches the route definition: /tenants/{tenant_id}/...
    tenant_id: str = Path(...),
) -> IdentityContext:
    """
    FastAPI dependency that enforces tenant membership without mutating IdentityContext.

    On success:
      - Attaches the resolved canonical UCP tenant ID to ``request.state.ucp_tenant_id``.

    Raises:
        HTTP 401 — if the request is not authenticated.
        HTTP 403 — if the principal is not authorized to access the requested tenant.
    """
    identity = resolve_identity(request)
    if identity is None:
        logger.error("tenant_guard_auth_required", requested_tenant_id=tenant_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TENANT_GUARD_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if identity.is_platform_admin:
        canonical_tenant_id = await _resolve_canonical_tenant_id(
            tenant_id=tenant_id,
            identity=identity,
            session=session,
            tenant_repo_factory=tenant_repo_factory,
        )
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    if tenant_id in identity.authorized_tenants or identity.tenant_id == tenant_id:
        canonical_tenant_id = str(identity.tenant_mapping.get(tenant_id, tenant_id))
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    canonical_tenant_id = str(identity.tenant_mapping.get(tenant_id, tenant_id))
    if (
        canonical_tenant_id in identity.authorized_tenants
        or identity.tenant_id == canonical_tenant_id
    ):
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    authz_runtime, _ = resolve_runtime_and_db(request)
    if authz_runtime is not None and await authz_runtime.has_hierarchical_tenant_access(
        session=session,
        user_id=identity.subject,
        target_tenant_id=canonical_tenant_id,
    ):
        request.state.ucp_tenant_id = canonical_tenant_id
        return identity

    logger.error(
        "tenant_authorization_failed",
        requested_tenant_id=tenant_id,
        canonical_tenant_id=canonical_tenant_id,
        context_tenant_id=identity.tenant_id,
        authorized_tenants=sorted(identity.authorized_tenants),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"User does not belong to tenant {tenant_id}.",
    )
