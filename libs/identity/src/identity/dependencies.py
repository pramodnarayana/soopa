"""
FastAPI Dependencies for Identity and Tenant Resolution.
Follows Hexagonal Architecture by adapting the HTTP layer to the Identity domain.
"""

import contextlib
import hashlib
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from config.settings import get_settings
from database.models import DatabaseShard, Tenant
from database.session import get_global_session
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity.application.use_cases import ResolveTenantUseCase
from identity.infrastructure.repositories import SQLAlchemyIdentityRepository

logger = logging.getLogger(__name__)

# Use Authorization Code flow for proper ZITADEL SSO integration via Swagger UI
_settings = get_settings()
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=_settings.identity.authorization_url,
    tokenUrl=_settings.identity.token_url,
    scopes={"openid": "OpenID Connect", "profile": "Profile information", "email": "Email address"},
    auto_error=False,
)

# Simple in-memory cache: { cache_key: (payload, expiry_time) }
_userinfo_cache: dict[str, tuple[dict[str, Any], float]] = {}
CACHE_TTL = 60.0  # seconds
MAX_CACHE_SIZE = 1000


async def get_raw_jwt(token: str | None = Depends(oauth2_scheme)) -> dict[str, Any]:
    """
    Extracts and validates the opaque Access Token by querying the Zitadel UserInfo endpoint.
    Maintains a 60-second TTL cache to prevent network spam.
    (Kept name get_raw_jwt to avoid breaking other files relying on this name)
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = time.time()
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()

    if cache_key in _userinfo_cache:
        payload, expiry = _userinfo_cache[cache_key]
        if now < expiry:
            return payload
        else:
            del _userinfo_cache[cache_key]

    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                settings.identity.userinfo_url, headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict) or "sub" not in payload:
                raise ValueError("Payload missing expected structure")

            payload_dict = payload

            # Normalize identity provider specific role claims into a standard format
            # This prevents Zitadel implementation details from leaking into the core application
            zitadel_roles = payload_dict.pop("urn:zitadel:iam:org:project:roles", {})
            if isinstance(zitadel_roles, dict):
                payload_dict["roles"] = list(zitadel_roles.keys())
            elif isinstance(zitadel_roles, list):
                payload_dict["roles"] = zitadel_roles
            else:
                payload_dict["roles"] = []

            # Bounded eviction
            if len(_userinfo_cache) >= MAX_CACHE_SIZE:
                _userinfo_cache.pop(next(iter(_userinfo_cache)))

            # Save to cache
            _userinfo_cache[cache_key] = (payload_dict, now + CACHE_TTL)
            return payload_dict
    except httpx.HTTPError as e:
        logger.error(f"UserInfo Validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_identity_repository(
    global_session: AsyncSession = Depends(get_global_session),
) -> AsyncGenerator[SQLAlchemyIdentityRepository, None]:
    """Dependency that yields a repository bound to the Global database session."""
    yield SQLAlchemyIdentityRepository(global_session)


async def get_resolve_tenant_use_case(
    repo: SQLAlchemyIdentityRepository = Depends(get_identity_repository),
) -> ResolveTenantUseCase:
    """Dependency that constructs the pure Application use case."""
    return ResolveTenantUseCase(repo)


async def get_current_tenant_id(
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    use_case: ResolveTenantUseCase = Depends(get_resolve_tenant_use_case),
) -> int:
    """
    Resolves the external user email from the JWT to our internal global DB tenant_id.
    """
    email = token_payload.get("email") or token_payload.get("preferred_username")
    name = token_payload.get("name")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not contain an email or preferred_username claim",
        )

    try:
        return await use_case.execute(str(email), str(name) if name else "")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


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
