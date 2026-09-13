from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from database.provider import DatabaseProvider
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from ucp.adapters.inbound.workers.ucp_event_dispatcher import UcpEventDispatcher
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.app_subscription_manager import AppSubscriptionManager
from ucp.application.use_cases.tenants.tenant_deleted_handler import TenantDeletedEventHandler
from ucp.config.settings import AppSettings
from ucp.domain.constants import UcpEventType
from ucp.ports.outbound.ucp_event_consumer_port import UcpEventMessage
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the UCP Worker."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.database_url = settings.database_url
        self.db_provider = DatabaseProvider.from_url(self.database_url)
        self.session_factory = self.db_provider.session_factory

        self.events_dispatcher: UcpEventDispatcher | None = None
        self.events_consumer: SqsConsumerManager | None = None

    def wire(self) -> None:
        self._wire_events_consumer()

    def _register_tenant_handlers(
        self,
        consumer: UcpEventDispatcher,
        tenant_deleted_handler: TenantDeletedEventHandler,
    ) -> None:
        async def tenant_deleted_event_handler(event: UcpEventMessage) -> None:
            payload = event.payload
            tenant_id = payload.get("tenant_id") or event.tenant_id
            if tenant_id:
                await tenant_deleted_handler.handle(str(tenant_id))
            else:
                logger.error("tenant_deleted_missing_tenant_id", event_id=event.id)

        consumer.subscribe(UcpEventType.TENANT_DELETED.value, tenant_deleted_event_handler)

    def _wire_events_consumer(self) -> None:
        @asynccontextmanager
        async def uow_factory() -> AsyncGenerator[UcpUnitOfWorkPort, None]:
            async with self.session_factory() as session:
                yield SqlAlchemyUcpUnitOfWork(session)

        provisioner = AppSubscriptionManager(uow_factory)
        tenant_deleted_handler = TenantDeletedEventHandler(uow_factory)

        self.events_dispatcher = UcpEventDispatcher()

        consumer = self.events_dispatcher
        consumer.subscribe(UcpEventType.APP_SUBSCRIBED.value, provisioner.handle_app_subscribed)
        consumer.subscribe(UcpEventType.APP_UNSUBSCRIBED.value, provisioner.handle_app_unsubscribed)

        self._register_tenant_handlers(consumer, tenant_deleted_handler)

        # Cron-triggered scheduled jobs are handled by jobs_consumer.

        ucp_identity_sync_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs_ucp_identity_sync_queue_url,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self.events_consumer = SqsConsumerManager(
            consumer=ucp_identity_sync_consumer,
            queue_name="ucp-events.fifo",
            handler=self.events_dispatcher.dispatch,
        )

    async def dispose(self) -> None:
        if self.db_provider:
            await self.db_provider.close()
