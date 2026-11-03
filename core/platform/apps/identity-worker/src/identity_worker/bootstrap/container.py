from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from identity.adapters.outbound.zitadel.machine_key_auth import ZitadelMachineTokenProvider
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from shttp import HttpClient
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
from identity_worker.adapters.outbound.identity_provider.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_projects_adapter import (
    ZitadelProjectsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_users_adapter import (
    ZitadelUsersAdapter,
)
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
        self._zitadel_client: HttpClient | None = None
        self.events_dispatcher: IdentityEventDispatcher | None = None
        self.events_consumer: SqsConsumerManager | None = None

    def wire(self) -> None:
        self._wire_events_consumer()

    def _wire_events_consumer(self) -> None:
        allow_private_ips = self.settings.identity.allow_private_ips
        token_provider = ZitadelMachineTokenProvider(
            api_url=self.settings.zitadel_api_url,
            machine_key=self.settings.zitadel_machine_key,
            allow_private_ips=allow_private_ips,
        )
        zitadel_client = HttpClient(
            base_url=self.settings.zitadel_api_url or None,
            token_provider=token_provider,
            default_headers={"Accept": "application/json"},
            allow_private_ips=allow_private_ips,
        )
        self._zitadel_client = zitadel_client

        project_provider = ZitadelProjectsAdapter(
            http_client=zitadel_client,
            settings=self.settings,
        )
        org_provider = ZitadelOrganizationsAdapter(
            http_client=zitadel_client,
            project_provider=project_provider,
            settings=self.settings,
        )
        idp_users = ZitadelUsersAdapter(
            http_client=zitadel_client,
            settings=self.settings,
        )

        identity_service = IdentitySyncService(
            organization_provider=org_provider,
            user_identity_provider=idp_users,
            uow_factory=lambda: create_identity_sync_uow(self.db_provider.session),
        )

        self.events_dispatcher = IdentityEventDispatcher()
        register_identity_handlers(self.events_dispatcher, identity_service)

        identity_sync_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs_identity_sync_queue_url,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self.events_consumer = SqsConsumerManager(
            consumer=identity_sync_consumer,
            queue_name="identity-events.fifo",
            handler=self.events_dispatcher.dispatch_raw,
        )

    async def dispose(self) -> None:
        if self._zitadel_client is not None:
            await self._zitadel_client.close()
        await self.db_provider.close()
