import os

from dependency_injector import containers, providers

from edi.adapters.aws_secrets_manager import AwsSecretsManagerAdapter
from edi.adapters.httpx_as2_tester import HttpxAS2TesterAdapter
from edi.adapters.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from edi.adapters.sqs_queue import SQSMessageQueueAdapter
from edi.adapters.tenant_repository import SqlAlchemyTenantRepository
from edi.adapters.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork,
    SqlAlchemyDataPlaneUnitOfWork,
)
from edi.adapters.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory
from edi.services.as2_receiver_service import As2ReceiverService


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the EDI bounded context.
    """

    wiring_config = containers.WiringConfiguration(
        packages=[
            "edi.dependencies",
        ]
    )

    # -----------------------------------------------------------------------
    # External Adapters & Providers (Stateless singletons / factories)
    # -----------------------------------------------------------------------
    sftp_tester = providers.Singleton(ParamikoSftpTesterAdapter)
    as2_tester = providers.Singleton(HttpxAS2TesterAdapter)
    vault_port = providers.Singleton(AwsSecretsManagerAdapter)

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
    # Note: For As2ReceiverService, dp_factory is required, but it relies on
    # FastAPI's request.app.state.db_router, so we'll inject dependencies dynamically
    as2_receiver_service = providers.Factory(
        As2ReceiverService,
        vault=vault_port,
    )
