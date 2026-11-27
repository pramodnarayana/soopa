from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from identity.adapters.outbound.casdoor.casdoor_admin_adapter import (
    CasdoorAdminAdapter,
    CasdoorAdminOptions,
)
from pubsub.domain.dtos import TopicSubscriptionSpec
from pubsub.domain.enums import PlatformTopicName
from pubsub.ports.consumer_manager_port import ConsumerManagerPort
from pubsub.provider import PubSubProvider
from sqlalchemy.ext.asyncio import AsyncSession

from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.adapters.inbound.workers.identity_event_handlers import (
    register_identity_handlers,
)
from identity_worker.adapters.outbound.database.identity_sync_repository import (
    SqlAlchemyIdentitySyncRepository,
)
from identity_worker.adapters.outbound.database.uow import SqlAlchemyIdentitySyncUnitOfWork
from identity_worker.application.use_cases.identity_sync_service import IdentitySyncService
from identity_worker.config.settings import AppSettings, get_settings

logger = structlog.get_logger(__name__)


def create_identity_sync_uow(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> SqlAlchemyIdentitySyncUnitOfWork:
    """Composition root factory assembling SqlAlchemyIdentitySyncUnitOfWork."""
    return SqlAlchemyIdentitySyncUnitOfWork(
        session_factory,
        repo_factory=SqlAlchemyIdentitySyncRepository,
    )


class WorkerContainer:
    """Dependency Injection container for the Identity Worker."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()

        database_url = self.settings.database_url
        if not database_url:
            raise ValueError("database_url is required in Settings")

        self.database_url = normalize_to_asyncpg(database_url)
        self.db_provider = DatabaseProvider.from_url(self.database_url)
        self._idp_admin: CasdoorAdminAdapter | None = None
        self.events_dispatcher: IdentityEventDispatcher | None = None
        self.events_consumer: ConsumerManagerPort | None = None

    def wire(self) -> None:
        self._wire_events_consumer()

    def _wire_events_consumer(self) -> None:
        idp_admin = CasdoorAdminAdapter(
            options=CasdoorAdminOptions(
                endpoint=self.settings.idp_api_url or self.settings.identity.issuer,
                client_id=self.settings.identity.admin_client_id,
                client_secret=self.settings.identity.admin_client_secret,
                default_organization=self.settings.identity.global_realm,
                allow_private_ips=self.settings.identity.allow_private_ips,
            )
        )
        self._idp_admin = idp_admin

        identity_service = IdentitySyncService(
            idp_admin=idp_admin,
            uow_factory=lambda: create_identity_sync_uow(self.db_provider.session),
            default_global_realm=self.settings.identity.global_realm,
            default_user_password=self.settings.idp_default_user_password or None,
        )

        self.events_dispatcher = IdentityEventDispatcher()
        register_identity_handlers(self.events_dispatcher, identity_service)

        self.events_consumer = PubSubProvider.create_consumer_manager(
            source_uri=self.settings.sqs_identity_sync_queue_url,
            handler=self.events_dispatcher.dispatch_raw,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
            transport=self.settings.pubsub_transport,
            session_factory=self.db_provider.session,
            database_url=self.database_url,
            subscribe_topics=(
                TopicSubscriptionSpec(
                    topic_name=PlatformTopicName.PLATFORM_EVENTS.value,
                    event_types=("tenant.", "app.", "user."),
                ),
            ),
        )

    async def dispose(self) -> None:
        if self._idp_admin is not None:
            await self._idp_admin.close()
        await self.db_provider.close()
