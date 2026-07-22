import contextlib
import os
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from config.settings import get_settings
from database.base_repository import GlobalSession
from database.models import DatabaseShard, Tenant
from database.session import get_global_session
from fastapi import Depends, Header, HTTPException, Request, status
from identity.adapters.outbound.zitadel.jwks_token_verifier import (
    ZitadelTokenVerifier,
    ZitadelTokenVerifierOptions,
)
from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import IdentityContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.adapters.api_token_repository import SqlAlchemyApiTokenRepository
from api.adapters.httpx_as2_tester import HttpxAS2TesterAdapter
from api.adapters.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from api.adapters.sqs_queue import SQSMessageQueueAdapter
from api.adapters.tenant_repository import SqlAlchemyTenantRepository
from api.adapters.vault import vault
from api.auth.api_key import get_tenant_id_from_api_key
from api.core.authorization import AuthorizationService
from api.core.uow import UnitOfWork
from api.ports.api_token_repository import ApiTokenRepositoryPort
from api.ports.as2_tester import AS2TesterPort
from api.ports.message_queue import MessageQueuePort
from api.ports.sftp_tester import SftpTesterPort
from api.ports.tenant_repository import TenantRepositoryPort
from api.ports.vault import VaultPort

_settings = get_settings()
token_verifier = ZitadelTokenVerifier(
    ZitadelTokenVerifierOptions(
        issuer=_settings.identity.issuer,
        audience=_settings.identity.audience,
        jwks_url=_settings.identity.jwks_url,
    )
)

async def get_identity_context(
    authorization: str | None = Header(default=None),
) -> IdentityContext:
    try:
        return await authenticate_bearer_token(authorization, token_verifier)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_raw_jwt(
    identity: IdentityContext = Depends(get_identity_context),
) -> dict[str, Any]:
    """Compatibility layer for legacy routes expecting raw token claims."""
    return identity.claims


async def get_current_tenant_id(
    identity: IdentityContext = Depends(get_identity_context),
) -> int:
    """Extracts tenant ID dynamically from the validated JWT."""
    try:
        return int(identity.tenant_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not contain a valid urn:zitadel:iam:org:id claim for tenant isolation.",
        ) from exc


async def get_tenant_session_for_id(
    request: Request,
    tenant_id: int,
    global_session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """Yields an AsyncSession bound to the database shard for a given tenant."""
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
        raise RuntimeError(f"Tenant {tenant_id} not found in global database")

    tenant, shard = row
    async_gen_tenant = db_router.get_tenant_session(tenant_id, shard.name, shard.dsn)
    tenant_session: AsyncSession = await async_gen_tenant.__anext__()

    try:
        yield tenant_session
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen_tenant.__anext__()


async def get_tenant_session(
    request: Request,
    tenant_id: int = Depends(get_current_tenant_id),
    global_session: AsyncSession = Depends(get_global_session),
) -> AsyncGenerator[AsyncSession, None]:
    """Yields an AsyncSession using the JWT's resolved tenant_id."""
    async for session in get_tenant_session_for_id(request, tenant_id, global_session):
        yield session


@lru_cache
def get_sftp_tester() -> SftpTesterPort:
    """Returns the Paramiko-based SFTP connection tester."""
    return ParamikoSftpTesterAdapter()


@lru_cache
def get_as2_tester() -> AS2TesterPort:
    """Returns the httpx-based AS2 connection tester."""
    return HttpxAS2TesterAdapter()


def get_vault() -> VaultPort:
    return vault


@lru_cache
def get_message_queue() -> MessageQueuePort:
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    return SQSMessageQueueAdapter(endpoint_url=endpoint_url)


async def get_uow(
    global_session: GlobalSession = Depends(get_global_session),
    # Optional tenant_session for platform admin routes
    # How to handle this? Best is to not inject tenant_session by default unless requested.
) -> UnitOfWork:
    return UnitOfWork(global_session=global_session)


async def get_tenant_uow(
    global_session: GlobalSession = Depends(get_global_session),
    tenant_session: AsyncSession = Depends(get_tenant_session),
) -> UnitOfWork:
    return UnitOfWork(global_session=global_session, tenant_session=tenant_session)


async def get_m2m_tenant_uow(
    request: Request,
    tenant_id: int = Depends(get_tenant_id_from_api_key),
    global_session: GlobalSession = Depends(get_global_session),
) -> AsyncGenerator[UnitOfWork, None]:
    """
    Constructs a UnitOfWork dynamically without relying on Zitadel JWTs.
    Useful for Machine-to-Machine routes that authenticate via API keys.
    """
    async for tenant_session in get_tenant_session_for_id(request, tenant_id, global_session):
        yield UnitOfWork(global_session=global_session, tenant_session=tenant_session)


def require_platform_admin(tenant_id: int = Depends(get_current_tenant_id)) -> int:
    """
    Dependency that enforces the user belongs to Tenant 0 (Platform Admin).
    """
    if tenant_id != 0:
        raise HTTPException(
            status_code=403,
            detail="Forbidden. This action requires Platform Admin (Tenant 0) privileges.",
        )
    return tenant_id


def get_tenant_repo(
    session: GlobalSession = Depends(get_global_session),
) -> TenantRepositoryPort:
    return SqlAlchemyTenantRepository(session)


def get_api_token_repo(
    session: GlobalSession = Depends(get_global_session),
) -> ApiTokenRepositoryPort:
    """Yields the API token repository bound to the global (control plane) session."""
    return SqlAlchemyApiTokenRepository(session)


def get_authorization_service(
    tenant_repo: TenantRepositoryPort = Depends(get_tenant_repo),
) -> AuthorizationService:
    return AuthorizationService(tenant_repo)


async def get_current_user_profile(
    tenant_id: int = Depends(get_current_tenant_id),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
    auth_service: AuthorizationService = Depends(get_authorization_service),
) -> dict[str, Any]:
    roles = token_payload.get("roles", [])
    if isinstance(roles, dict):
        roles = list(roles.keys())

    is_platform_admin = tenant_id == 0 or "Platform_Admin" in roles

    return await auth_service.get_authorization_profile(
        tenant_id=tenant_id,
        is_platform_admin=is_platform_admin,
        current_rls_tenant=None,
        roles=roles,
    )
