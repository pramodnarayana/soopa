from collections.abc import Sequence

from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from dependency_injector import containers, providers
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.ports.shard_outbox_drain_port import ShardOutboxDrainPort
from secret_store import PlatformSecretStoreSettings, SecretStoreProvider
from security.provider import SecurityProvider
from seedwork.infra.config_models import PlatformAwsSettings
from sqlalchemy.ext.asyncio import AsyncSession
from storage import PlatformStorageSettings, StorageProvider
from strace.adapters import SqlAlchemyTraceRepository

from edi.adapters.outbound.database.control_plane.as2_partner_repository import (
    SqlAlchemyAS2TradingPartnerRepository,
)
from edi.adapters.outbound.database.control_plane.as2_partnership_repository import (
    SqlAlchemyAS2PartnershipRepository,
)
from edi.adapters.outbound.database.control_plane.edi_header_repository import (
    SqlAlchemyEdiHeaderRepository,
)
from edi.adapters.outbound.database.control_plane.inbound_route_repository import (
    SqlAlchemyInboundRouteRepository,
)
from edi.adapters.outbound.database.control_plane.outbound_route_repository import (
    SqlAlchemyOutboundRouteRepository,
)
from edi.adapters.outbound.database.control_plane.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
)
from edi.adapters.outbound.database.control_plane.settings_repository import (
    SqlAlchemySettingsRepository,
)
from edi.adapters.outbound.database.control_plane.sftp_partner_repository import (
    SqlAlchemySFTPPartnerRepository,
)
from edi.adapters.outbound.database.control_plane.tenant_repository import (
    SqlAlchemyTenantRepository,
)
from edi.adapters.outbound.database.control_plane.uow import SqlAlchemyControlPlaneUnitOfWork
from edi.adapters.outbound.database.control_plane.webhook_repository import (
    SqlAlchemyWebhookRepository,
)
from edi.adapters.outbound.database.data_plane.api_gateway_repository import (
    SqlAlchemyApiGatewayRepository,
)
from edi.adapters.outbound.database.data_plane.as2_partner_repository import (
    SqlAlchemyDataPlaneAS2PartnerRepository,
)
from edi.adapters.outbound.database.data_plane.as2_partnership_repository import (
    SqlAlchemyDataPlaneAS2PartnershipRepository,
)
from edi.adapters.outbound.database.data_plane.edi_header_repository import (
    SqlAlchemyDataPlaneEdiHeaderRepository,
)
from edi.adapters.outbound.database.data_plane.edi_json_repository import (
    SqlAlchemyEdiJsonRepository,
)
from edi.adapters.outbound.database.data_plane.edi_message_repository import (
    SqlAlchemyEdiMessageRepository,
)
from edi.adapters.outbound.database.data_plane.inbound_route_repository import (
    SqlAlchemyDataPlaneInboundRouteRepository,
)
from edi.adapters.outbound.database.data_plane.outbound_route_repository import (
    SqlAlchemyDataPlaneOutboundRouteRepository,
)
from edi.adapters.outbound.database.data_plane.outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)
from edi.adapters.outbound.database.data_plane.sftp_partner_repository import (
    SqlAlchemyDataPlaneSFTPPartnerRepository,
)
from edi.adapters.outbound.database.data_plane.trace_specs import (
    EDI_TRACE_EVENT_SPEC,
    EDI_TRACE_STAGE_SPECS,
)
from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.database.data_plane.webhook_repository import (
    SqlAlchemyDataPlaneWebhookRepository,
)
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.adapters.outbound.database.tenant_resolver import SqlAlchemyTenantResolver
from edi.adapters.outbound.database.tenant_uow_provider import SqlAlchemyTenantUoWProvider
from edi.adapters.outbound.database.uow_factory import SqlAlchemyDataPlaneUnitOfWorkFactory
from edi.adapters.outbound.http.httpx_as2_tester_adapter import HttpxAS2TesterAdapter
from edi.adapters.outbound.pipeline.storage import PlatformStorageAdapter
from edi.adapters.outbound.security.certificates import CryptographyCertificateGeneratorAdapter
from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from edi.adapters.outbound.sftp.paramiko_sftp_tester import ParamikoSftpTesterAdapter
from edi.adapters.outbound.transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter
from edi.bootstrap.publisher_factory import create_edi_pipeline_publisher
from edi.domain.constants import EdiConstants
from edi.domain.enums import EdiOutboxSource
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.tenant_port import TenantPort


def create_edi_control_plane_uow(global_session: AsyncSession) -> SqlAlchemyControlPlaneUnitOfWork:
    """Composition root factory assembling SqlAlchemyControlPlaneUnitOfWork with concrete repositories."""
    gs = GlobalSession(global_session)
    return SqlAlchemyControlPlaneUnitOfWork(
        global_session,
        as2_partners=SqlAlchemyAS2TradingPartnerRepository(gs),
        as2_partnerships=SqlAlchemyAS2PartnershipRepository(gs),
        inbound_routes=SqlAlchemyInboundRouteRepository(gs),
        outbound_routes=SqlAlchemyOutboundRouteRepository(gs),
        sftp_partners=SqlAlchemySFTPPartnerRepository(gs),
        tenants=SqlAlchemyTenantRepository(gs),
        edi_headers=SqlAlchemyEdiHeaderRepository(gs),
        control_plane_outbox=SqlAlchemyControlPlaneOutboxRepository(gs),
        settings=SqlAlchemySettingsRepository(gs),
        webhooks=SqlAlchemyWebhookRepository(gs),
    )


def create_edi_data_plane_uow(
    tenant_session: AsyncSession,
    storage: StoragePort,
) -> SqlAlchemyDataPlaneUnitOfWork:
    """Composition root factory assembling SqlAlchemyDataPlaneUnitOfWork with concrete repositories."""
    typed_tenant_session = TenantSession(tenant_session)
    return SqlAlchemyDataPlaneUnitOfWork(
        tenant_session,
        edi_messages=SqlAlchemyEdiMessageRepository(typed_tenant_session, storage),
        edi_jsons=SqlAlchemyEdiJsonRepository(typed_tenant_session, storage),
        api_gateway_receipts=SqlAlchemyApiGatewayRepository(typed_tenant_session),
        traces=SqlAlchemyTraceRepository(
            tenant_session,
            event_spec=EDI_TRACE_EVENT_SPEC,
            stage_specs=EDI_TRACE_STAGE_SPECS,
        ),
        outbox=SqlAlchemyDataPlaneOutboxRepository(session=tenant_session),
        inbound_routes=SqlAlchemyDataPlaneInboundRouteRepository(session=tenant_session),
        outbound_routes=SqlAlchemyDataPlaneOutboundRouteRepository(session=tenant_session),
        sftp_partners=SqlAlchemyDataPlaneSFTPPartnerRepository(session=tenant_session),
        as2_partners=SqlAlchemyDataPlaneAS2PartnerRepository(session=tenant_session),
        as2_partnerships=SqlAlchemyDataPlaneAS2PartnershipRepository(session=tenant_session),
        webhooks=SqlAlchemyDataPlaneWebhookRepository(session=tenant_session),
        edi_headers=SqlAlchemyDataPlaneEdiHeaderRepository(session=tenant_session),
    )


def create_edi_dp_uow_factory(
    *,
    resolver: TenantPort,
    db_router: DatabaseRouterPort,
    storage: StoragePort,
) -> SqlAlchemyDataPlaneUnitOfWorkFactory:
    """Composition root factory assembling SqlAlchemyDataPlaneUnitOfWorkFactory."""
    return SqlAlchemyDataPlaneUnitOfWorkFactory(
        resolver=resolver,
        db_router=db_router,
        uow_builder=lambda session: create_edi_data_plane_uow(
            tenant_session=session,
            storage=storage,
        ),
    )


def create_edi_dp_filtered_outbox_drain_repo(
    *,
    db_router: DatabaseRouterPort,
    event_types: Sequence[str] | None = None,
) -> ShardOutboxDrainPort:
    """Composition root factory assembling a stage-filtered SqlAlchemyShardedOutboxRepository for direct Single-Queue EDI worker draining."""
    return SqlAlchemyShardedOutboxRepository(
        db_router=db_router,
        model_cls=DataPlaneOutbox,
        app_slug=EdiConstants.EDI_APP_SLUG.value,
        source=EdiOutboxSource.EDI_DATA_PLANE.value,
        min_pending_age_seconds=0,
        event_types=event_types,
    )


def create_edi_tenant_uow_provider(
    *,
    resolver: TenantPort,
    db_router: DatabaseRouterPort,
    storage_settings: PlatformStorageSettings,
    aws_settings: PlatformAwsSettings | None = None,
) -> SqlAlchemyTenantUoWProvider:
    """Composition root factory assembling SqlAlchemyTenantUoWProvider with centralized platform storage."""
    storage = PlatformStorageAdapter.from_settings(
        storage_settings,
        aws_settings=aws_settings,
    )
    return SqlAlchemyTenantUoWProvider(
        resolver=resolver,
        db_router=db_router,
        uow_builder=lambda session: create_edi_data_plane_uow(
            tenant_session=session,
            storage=storage,
        ),
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
    certificate_generator = providers.Singleton(CryptographyCertificateGeneratorAdapter)
    field_encryption = providers.Singleton(SecurityProvider.get_fernet_cipher)
    edi_ast_codec = providers.Singleton(BotsEDIAdapter)
    sftp_tester = providers.Singleton(
        ParamikoSftpTesterAdapter,
        allow_local=config.allow_private_ips,
    )
    as2_tester = providers.Singleton(
        HttpxAS2TesterAdapter,
        allow_private_ips=config.allow_private_ips,
        crypto_service=crypto_service,
    )
    secrets_settings = providers.Dependency(instance_of=PlatformSecretStoreSettings)
    storage_settings = providers.Dependency(instance_of=PlatformStorageSettings)
    aws_settings = providers.Dependency(instance_of=PlatformAwsSettings)

    vault_port = providers.Singleton(
        SecretStoreProvider.from_settings,
        settings=secrets_settings,
        aws_settings=aws_settings,
    )
    payload_storage = providers.Singleton(
        StorageProvider.from_settings,
        settings=storage_settings,
        aws_settings=aws_settings,
    )
    storage = providers.Singleton(
        PlatformStorageAdapter,
        payload_storage=payload_storage,
    )

    # -----------------------------------------------------------------------
    # Repositories and Units of Work
    # Session dependencies must be passed at runtime using kwargs.
    # -----------------------------------------------------------------------
    tenant_resolver = providers.Dependency(instance_of=SqlAlchemyTenantResolver)
    tenant_repo = providers.Factory(SqlAlchemyTenantRepository)
    cp_uow = providers.Factory(create_edi_control_plane_uow)
    dp_uow = providers.Factory(create_edi_data_plane_uow, storage=storage)
    dp_factory = providers.Factory(create_edi_dp_uow_factory, storage=storage)

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
