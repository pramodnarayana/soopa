import os
from functools import lru_cache
from typing import Any

from database.session import get_global_session
from fastapi import Depends, HTTPException

# Import tenant_session from identity
from identity.dependencies import get_current_tenant_id, get_raw_jwt, get_tenant_session
from sqlalchemy.ext.asyncio import AsyncSession

from api.adapters.httpx_as2_tester import HttpxAS2TesterAdapter
from api.adapters.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from api.adapters.repository import (
    SqlAlchemyControlPlaneRepository,
    SqlAlchemyDataPlaneRepository,
    SqlAlchemyTenantRepository,
)
from api.adapters.sqs_queue import SQSMessageQueueAdapter
from api.adapters.vault import vault
from api.core.authorization import AuthorizationService
from api.core.uow import UnitOfWork
from api.ports.as2_tester import AS2TesterPort
from api.ports.message_queue import MessageQueuePort
from api.ports.repository import (
    ControlPlaneRepositoryPort,
    DataPlaneRepositoryPort,
    TenantRepositoryPort,
)
from api.ports.sftp_tester import SftpTesterPort
from api.ports.vault import VaultPort


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


def get_control_plane_repo(
    session: AsyncSession = Depends(get_global_session),
) -> ControlPlaneRepositoryPort:
    return SqlAlchemyControlPlaneRepository(session)


def get_data_plane_repo(
    session: AsyncSession = Depends(get_tenant_session),
) -> DataPlaneRepositoryPort:
    return SqlAlchemyDataPlaneRepository(session)


async def get_uow(
    global_session: AsyncSession = Depends(get_global_session),
    # Optional tenant_session for platform admin routes
    # How to handle this? Best is to not inject tenant_session by default unless requested.
) -> UnitOfWork:
    return UnitOfWork(global_session=global_session)


async def get_tenant_uow(
    global_session: AsyncSession = Depends(get_global_session),
    tenant_session: AsyncSession = Depends(get_tenant_session),
) -> UnitOfWork:
    return UnitOfWork(global_session=global_session, tenant_session=tenant_session)


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
    session: AsyncSession = Depends(get_global_session),
) -> TenantRepositoryPort:
    return SqlAlchemyTenantRepository(session)


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
