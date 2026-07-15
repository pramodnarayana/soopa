import os
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from database.session import get_global_session
from fastapi import Depends, HTTPException, Request
from identity.dependencies import (
    get_current_tenant_id,
    get_raw_jwt,
    get_tenant_session,
    get_tenant_session_for_id,
)
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


from api.adapters.as2_partner_repository import SqlAlchemyAS2TradingPartnerRepository  # noqa: E402
from api.adapters.as2_partnership_repository import SqlAlchemyAS2PartnershipRepository  # noqa: E402
from api.adapters.edi_header_repository import SqlAlchemyEdiHeaderRepository  # noqa: E402
from api.adapters.inbound_route_repository import SqlAlchemyInboundRouteRepository  # noqa: E402
from api.adapters.outbound_route_repository import SqlAlchemyOutboundRouteRepository  # noqa: E402
from api.adapters.sftp_repository import SqlAlchemySFTPPartnerRepository  # noqa: E402
from api.adapters.webhook_repository import SqlAlchemyWebhookRepository  # noqa: E402
from api.ports.as2_partner_repository import AS2TradingPartnerRepositoryPort  # noqa: E402
from api.ports.as2_partnership_repository import AS2PartnershipRepositoryPort  # noqa: E402
from api.ports.edi_header_repository import EdiHeaderRepositoryPort  # noqa: E402
from api.ports.inbound_route_repository import InboundRouteRepositoryPort  # noqa: E402
from api.ports.outbound_route_repository import OutboundRouteRepositoryPort  # noqa: E402
from api.ports.sftp_repository import SFTPPartnerRepositoryPort  # noqa: E402
from api.ports.webhook_repository import WebhookRepositoryPort  # noqa: E402


def get_as2_partner_repo(
    session: AsyncSession = Depends(get_global_session),
) -> AS2TradingPartnerRepositoryPort:
    return SqlAlchemyAS2TradingPartnerRepository(session)


def get_as2_partnership_repo(
    session: AsyncSession = Depends(get_global_session),
) -> AS2PartnershipRepositoryPort:
    return SqlAlchemyAS2PartnershipRepository(session)


def get_inbound_route_repo(
    session: AsyncSession = Depends(get_global_session),
) -> InboundRouteRepositoryPort:
    return SqlAlchemyInboundRouteRepository(session)


def get_outbound_route_repo(
    session: AsyncSession = Depends(get_global_session),
) -> OutboundRouteRepositoryPort:
    return SqlAlchemyOutboundRouteRepository(session)


def get_sftp_partner_repo(
    session: AsyncSession = Depends(get_global_session),
) -> SFTPPartnerRepositoryPort:
    return SqlAlchemySFTPPartnerRepository(session)


def get_webhook_repo(session: AsyncSession = Depends(get_global_session)) -> WebhookRepositoryPort:
    return SqlAlchemyWebhookRepository(session)


def get_edi_header_repo(
    session: AsyncSession = Depends(get_global_session),
) -> EdiHeaderRepositoryPort:
    return SqlAlchemyEdiHeaderRepository(session)


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


async def get_m2m_tenant_uow(
    request: Request,
    tenant_id: int = Depends(get_tenant_id_from_api_key),
    global_session: AsyncSession = Depends(get_global_session),
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
    session: AsyncSession = Depends(get_global_session),
) -> TenantRepositoryPort:
    return SqlAlchemyTenantRepository(session)


def get_api_token_repo(
    session: AsyncSession = Depends(get_global_session),
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
