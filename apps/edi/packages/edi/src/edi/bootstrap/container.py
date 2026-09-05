from dependency_injector import containers, providers
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter

from edi.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork,
    SqlAlchemyDataPlaneUnitOfWork,
)
from edi.adapters.outbound.database.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.adapters.outbound.pipeline.storage import S3StorageClient
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from edi.adapters.outbound.sftp.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    ProcessInboundAs2MessageUseCase,
)


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the EDI bounded context.
    """

    config = providers.Configuration()

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
        secrets_mount_path=config.secrets.mount_path,
    )
    storage = providers.Singleton(
        S3StorageClient,
        bucket_name=config.s3.bucket,
        endpoint_url=config.s3.endpoint_url,
        region=config.s3.region,
    )

    # -----------------------------------------------------------------------
    # Repositories and Units of Work
    # Session dependencies must be passed at runtime using kwargs.
    # -----------------------------------------------------------------------
    tenant_repo = providers.Factory(SqlAlchemyTenantRepository)
    cp_uow = providers.Factory(SqlAlchemyControlPlaneUnitOfWork)
    dp_uow = providers.Factory(SqlAlchemyDataPlaneUnitOfWork, storage=storage)
    dp_factory = providers.Factory(SqlAlchemyDataPlaneUnitOfWorkFactory, storage=storage)

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
