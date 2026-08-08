import os
from functools import lru_cache
from typing import Annotated

from database.base_repository import GlobalSession
from database.session import get_global_session
from fastapi import Depends, Request

from edi.adapters.httpx_as2_tester import HttpxAS2TesterAdapter
from edi.adapters.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from edi.adapters.sqs_queue import SQSMessageQueueAdapter
from edi.adapters.tenant_repository import SqlAlchemyTenantRepository
from edi.adapters.vault import vault
from edi.ports.as2_tester import AS2TesterPort
from edi.ports.message_queue import MessageQueuePort
from edi.ports.sftp_tester import SftpTesterPort
from edi.ports.tenant_repository import TenantRepositoryPort
from edi.ports.vault import VaultPort
from edi.services.as2_receiver_service import As2ReceiverService


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


def get_tenant_repo(
    session: Annotated[GlobalSession, Depends(get_global_session)],
) -> TenantRepositoryPort:
    return SqlAlchemyTenantRepository(session)


def get_as2_receiver_service(
    request: Request,
    global_session: Annotated[GlobalSession, Depends(get_global_session)],
    vault: Annotated[VaultPort, Depends(get_vault)],
) -> As2ReceiverService:
    from edi.adapters.uow_adapter import SqlAlchemyControlPlaneUnitOfWork
    from edi.adapters.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory

    control_plane_uow = SqlAlchemyControlPlaneUnitOfWork(global_session)
    dp_factory = SqlAlchemyDataPlaneUnitOfWorkFactory(
        global_session=global_session, db_router=request.app.state.db_router
    )
    return As2ReceiverService(
        control_plane_uow=control_plane_uow,
        dp_factory=dp_factory,
        vault=vault,
    )
