import os
from functools import lru_cache

from api.adapters.api_token_repository import SqlAlchemyApiTokenRepository
from api.adapters.httpx_as2_tester import HttpxAS2TesterAdapter
from api.adapters.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from api.adapters.sqs_queue import SQSMessageQueueAdapter
from api.adapters.tenant_repository import SqlAlchemyTenantRepository
from api.adapters.vault import vault
from api.ports.api_token_repository import ApiTokenRepositoryPort
from api.ports.as2_tester import AS2TesterPort
from api.ports.message_queue import MessageQueuePort
from api.ports.sftp_tester import SftpTesterPort
from api.ports.tenant_repository import TenantRepositoryPort
from api.ports.vault import VaultPort
from database.base_repository import GlobalSession
from database.session import get_global_session
from fastapi import Depends


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
    session: GlobalSession = Depends(get_global_session),
) -> TenantRepositoryPort:
    return SqlAlchemyTenantRepository(session)


def get_api_token_repo(
    session: GlobalSession = Depends(get_global_session),
) -> ApiTokenRepositoryPort:
    """Yields the API token repository bound to the global (control plane) session."""
    return SqlAlchemyApiTokenRepository(session)
