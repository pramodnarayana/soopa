"""
FastAPI Dependencies for Identity and Tenant Resolution.
Follows Hexagonal Architecture by adapting the HTTP layer to the Identity domain.
"""

import contextlib
import logging
from collections.abc import AsyncGenerator

from config.settings import get_settings
from database.models import DatabaseShard, Tenant
from database.session import get_global_session
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from soopa_identity import require_identity, IdentityContext
from soopa_identity.adapters.outbound.zitadel.jwks_token_verifier import (
    ZitadelTokenVerifier,
    ZitadelTokenVerifierOptions,
)

logger = logging.getLogger(__name__)

_settings = get_settings()
_verifier = ZitadelTokenVerifier(
    ZitadelTokenVerifierOptions(
        issuer=_settings.identity.issuer,
        audience=_settings.identity.audience,
        jwks_url=_settings.identity.jwks_url,
    )
)

async def get_current_identity(
    identity: IdentityContext = require_identity(_verifier),
) -> IdentityContext:
    """Returns the IdentityContext from the soopa_identity SDK."""
    return identity


async def get_current_tenant_id(
    identity: IdentityContext = Depends(get_current_identity),
    global_session: AsyncSession = Depends(get_global_session),
) -> int:
    """
    Resolves the external Zitadel organization ID to our internal global DB tenant_id.
    """
    org_id = identity.tenant_id
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not contain a tenant_id claim",
        )

    stmt = select(Tenant.id).where(Tenant.idp_tenant_id == org_id)
    result = await global_session.execute(stmt)
    tenant_id = result.scalar_one_or_none()
    
    if tenant_id is None:
        # Fallback for platform admin (no org id, or different structure)
        # We can adjust this if Zitadel assigns a specific org for platform admin
        if "Platform_Admin" in identity.roles:
            return 0
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant not provisioned in this environment",
        )
    return tenant_id


async def get_tenant_session_for_id(
    request: Request,
    tenant_id: int,
    global_session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields an AsyncSession dynamically bound to the correct database shard for a given tenant_id.
    """
    db_router = getattr(request.app.state, "db_router", None)
    if not db_router:
        raise RuntimeError("DatabaseRouter not initialized in app state")

    stmt = (
        select(Tenant, DatabaseShard)
        .join(DatabaseShard, Tenant.shard_id == DatabaseShard.id)
        .where(Tenant.id == tenant_id)
    )
    result = await global_session.execute(stmt)
    row = result.one_or_none()
    if not row:
        raise RuntimeError(f"Tenant {tenant_id} not found in database")

    tenant, shard = row
    shard_key = shard.name
    shard_url = shard.dsn

    async_gen_tenant = db_router.get_tenant_session(tenant_id, shard_key, shard_url)
    tenant_session: AsyncSession = await async_gen_tenant.__anext__()

    from identity.tenant_context import _tenant_id

    token = _tenant_id.set(tenant_id)

    try:
        yield tenant_session
    finally:
        _tenant_id.reset(token)
        with contextlib.suppress(StopAsyncIteration):
            await async_gen_tenant.__anext__()


async def get_tenant_session(
    request: Request,
    tenant_id: int = Depends(get_current_tenant_id),
    global_session: AsyncSession = Depends(get_global_session),
) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields an AsyncSession dynamically bound to the correct database shard,
    using Zitadel JWT authentication to resolve the tenant_id.
    """
    async for session in get_tenant_session_for_id(request, tenant_id, global_session):
        yield session
