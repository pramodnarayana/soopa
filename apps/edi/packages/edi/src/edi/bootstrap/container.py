from dependency_injector import containers, providers
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter

from edi.adapters.outbound.database.control_plane.tenant_repository import (
    SqlAlchemyTenantRepository,
)
from edi.adapters.outbound.database.control_plane.uow import SqlAlchemyControlPlaneUnitOfWork
from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.adapters.outbound.database.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.adapters.outbound.pipeline.storage import S3StorageClient
from edi.adapters.outbound.pubsub.publisher_factory import create_edi_pipeline_publisher
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from edi.adapters.outbound.sftp.paramiko_sftp_tester import ParamikoSftpTesterAdapter


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
    as2_tester = providers.Singleton(
        HttpxAS2TesterAdapter,
        allow_private_ips=config.allow_private_ips,
    )
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
    tenant_resolver = providers.Dependency(instance_of=TenantResolver)
    tenant_repo = providers.Factory(SqlAlchemyTenantRepository)
    cp_uow = providers.Factory(SqlAlchemyControlPlaneUnitOfWork)
    dp_uow = providers.Factory(SqlAlchemyDataPlaneUnitOfWork, storage=storage)
    dp_factory = providers.Factory(SqlAlchemyDataPlaneUnitOfWorkFactory, storage=storage)

    # -----------------------------------------------------------------------
    # Publisher
    # -----------------------------------------------------------------------
    outbox_publisher = providers.Singleton(
        create_edi_pipeline_publisher,
        compute_queue_url=config.sqs.compute_queue_url,
        orchestrator_queue_url=config.sqs.orchestrator_queue_url,
        deliver_queue_url=config.sqs.deliver_queue_url,
        region_name=config.aws.resolved_region,
        endpoint_url=config.aws.endpoint_url,
    )
