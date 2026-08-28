import os

from dependency_injector import containers, providers
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter

from edi.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork,
    SqlAlchemyDataPlaneUnitOfWork,
)
from edi.adapters.outbound.database.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.adapters.outbound.messaging.sqs_queue import SQSMessageQueueAdapter
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from edi.adapters.outbound.sftp.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase,
)
from edi.config.settings import get_settings


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the EDI bounded context.
    """

    wiring_config = containers.WiringConfiguration(
        packages=[
            "unified_api.adapters.inbound.http.dependencies.edi",
        ]
    )

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    crypto_service = providers.Singleton(SmimeCryptoService)
    sftp_tester = providers.Singleton(ParamikoSftpTesterAdapter)
    as2_tester = providers.Singleton(HttpxAS2TesterAdapter)
    vault_port = providers.Singleton(
        AwsSecretsManagerAdapter,
        secrets_mount_path=get_settings().secrets.mount_path,
    )

    message_queue = providers.Singleton(
        SQSMessageQueueAdapter,
        endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    )

    # -----------------------------------------------------------------------
    # Repositories and Units of Work
    # Session dependencies must be passed at runtime using kwargs.
    # -----------------------------------------------------------------------
    tenant_repo = providers.Factory(SqlAlchemyTenantRepository)
    cp_uow = providers.Factory(SqlAlchemyControlPlaneUnitOfWork)
    dp_uow = providers.Factory(SqlAlchemyDataPlaneUnitOfWork)
    dp_factory = providers.Factory(SqlAlchemyDataPlaneUnitOfWorkFactory)

    # -----------------------------------------------------------------------
    # Services
    # -----------------------------------------------------------------------
    # Note: control_plane_uow and dp_factory are session-scoped and must be
    # passed at runtime via kwargs. crypto_service is stateless and pre-wired.
    as2_receiver_service = providers.Factory(
        ProcessInboundAs2MessageUseCase,
        secret_store=vault_port,
        crypto_service=crypto_service,
    )
