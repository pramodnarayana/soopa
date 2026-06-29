import os
from functools import lru_cache

from database.session import get_global_session
from fastapi import Depends, HTTPException

# Import tenant_session from identity
from identity.dependencies import get_current_tenant_id, get_tenant_session
from sqlalchemy.ext.asyncio import AsyncSession

from api.adapters.repository import (
    SqlAlchemyControlPlaneRepository,
    SqlAlchemyDataPlaneRepository,
)
from api.adapters.sqs_queue import SQSMessageQueueAdapter
from api.core.uow import UnitOfWork
from api.ports.message_queue import MessageQueuePort
from api.ports.repository import ControlPlaneRepositoryPort, DataPlaneRepositoryPort


@lru_cache
def get_message_queue() -> MessageQueuePort:
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    return SQSMessageQueueAdapter(endpoint_url=endpoint_url)


def get_control_plane_repo(
    session: AsyncSession,
) -> ControlPlaneRepositoryPort:
    return SqlAlchemyControlPlaneRepository(session)


def get_data_plane_repo(
    session: AsyncSession,
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
