import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from database.provider import DatabaseProvider
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from ucp.adapters.inbound.workers.ucp_event_dispatcher import UcpEventDispatcher
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.database.postgres_ucp_audit_log_cleanup_repository import (
    SqlAlchemyUcpAuditLogCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_idempotency_cleanup_repository import (
    SqlAlchemyUcpIdempotencyCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_outbox_cleanup_repository import (
    SqlAlchemyUcpOutboxCleanupRepository,
)
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.infrastructure_provisioner import InfrastructureProvisioner
from ucp.application.use_cases.tenants.tenant_deleted_handler import TenantDeletedEventHandler
from ucp.application.use_cases.ucp_audit_log_cleanup_use_case import UcpAuditLogCleanupUseCase
from ucp.application.use_cases.ucp_idempotency_cleanup_use_case import UcpIdempotencyCleanupUseCase
from ucp.bootstrap.config import get_settings
from ucp.domain.constants import UcpEventType
from ucp.ports.outbound.ucp_event_consumer_port import UcpEventMessage
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

from ucp_worker.adapters.inbound.jobs.ucp_audit_log_cleanup_job import UcpAuditLogCleanupJobHandler
from ucp_worker.adapters.inbound.jobs.ucp_idempotency_cleanup_job import (
    UcpIdempotencyCleanupJobHandler,
)
from ucp_worker.adapters.inbound.jobs.ucp_outbox_cleanup_job import UcpOutboxCleanupJobHandler
from ucp_worker.adapters.inbound.jobs.ucp_outbox_sweeper_job import UcpOutboxSweeperJobHandler
from ucp_worker.adapters.inbound.workers.ucp_job_dispatcher import UcpJobDispatcher
from ucp_worker.constants import UcpJobName

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the UCP Worker."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.database_url = os.environ.get("DATABASE_URL", "")
        self.db_provider = DatabaseProvider.from_url(self.database_url)
        self.session_factory = self.db_provider.session_factory

        self.outbox_relay: PostgresOutboxRelay | None = None
        self.events_dispatcher: UcpEventDispatcher | None = None
        self.events_consumer: SqsConsumerManager | None = None
        self.jobs_consumer: SqsConsumerManager | None = None

        self.sweeper_job_handler: UcpOutboxSweeperJobHandler | None = None
        self.outbox_cleanup_job_handler: UcpOutboxCleanupJobHandler | None = None
        self.idemp_cleanup_job_handler: UcpIdempotencyCleanupJobHandler | None = None
        self.audit_cleanup_job_handler: UcpAuditLogCleanupJobHandler | None = None

    def wire(self) -> None:
        outbox_repo = PostgresOutboxRepository(self.session_factory)
        outbox_pub = AwsSnsPublisher(
            topic_arn=self.settings.sns_tenant_events_topic_arn,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self._wire_scheduled_jobs(outbox_repo, outbox_pub)
        self._wire_outbox_relay(outbox_repo, outbox_pub)
        self._wire_events_consumer()
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(
        self, outbox_repo: PostgresOutboxRepository, outbox_pub: AwsSnsPublisher
    ) -> None:
        outbox_cleanup_repo = SqlAlchemyUcpOutboxCleanupRepository(self.session_factory)
        idemp_cleanup_repo = SqlAlchemyUcpIdempotencyCleanupRepository(self.session_factory)
        audit_cleanup_repo = SqlAlchemyUcpAuditLogCleanupRepository(self.session_factory)

        sweeper_use_case = OutboxSweeperUseCase(outbox_repo, outbox_pub)

        outbox_cleaner_use_case = OutboxCleanerUseCase(outbox_cleanup_repo)
        idemp_cleanup_use_case = UcpIdempotencyCleanupUseCase(idemp_cleanup_repo)
        audit_cleanup_use_case = UcpAuditLogCleanupUseCase(audit_cleanup_repo)

        self.sweeper_job_handler = UcpOutboxSweeperJobHandler(sweeper_use_case)
        self.outbox_cleanup_job_handler = UcpOutboxCleanupJobHandler(outbox_cleaner_use_case)
        self.idemp_cleanup_job_handler = UcpIdempotencyCleanupJobHandler(idemp_cleanup_use_case)
        self.audit_cleanup_job_handler = UcpAuditLogCleanupJobHandler(audit_cleanup_use_case)

    def _wire_outbox_relay(
        self, outbox_repo: PostgresOutboxRepository, outbox_pub: AwsSnsPublisher
    ) -> None:
        outbox_processor = OutboxProcessorUseCase(
            repository=outbox_repo,
            publisher=outbox_pub,
        )
        self.outbox_relay = PostgresOutboxRelay(
            processor=outbox_processor,
            database_url=self.database_url,
            listen_channel="ucp_outbox_wakeup",
        )

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

        provisioner = InfrastructureProvisioner(uow_factory)
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

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = UcpJobDispatcher()

        async def sweep_handler(message: dict[str, Any]) -> None:
            if self.sweeper_job_handler:
                await self.sweeper_job_handler.execute()

        async def outbox_cleanup_handler(message: dict[str, Any]) -> None:
            if self.outbox_cleanup_job_handler:
                await self.outbox_cleanup_job_handler.execute()

        async def idemp_cleanup_handler(message: dict[str, Any]) -> None:
            if self.idemp_cleanup_job_handler:
                await self.idemp_cleanup_job_handler.execute()

        async def audit_cleanup_handler(message: dict[str, Any]) -> None:
            if self.audit_cleanup_job_handler:
                await self.audit_cleanup_job_handler.execute()

        job_dispatcher.subscribe(UcpJobName.UCP_OUTBOX_SWEEPER.value, sweep_handler)
        job_dispatcher.subscribe(UcpJobName.UCP_OUTBOX_CLEANUP.value, outbox_cleanup_handler)
        job_dispatcher.subscribe(UcpJobName.UCP_IDEMPOTENCY_CLEANUP.value, idemp_cleanup_handler)
        job_dispatcher.subscribe(UcpJobName.UCP_AUDIT_LOG_CLEANUP.value, audit_cleanup_handler)

        jobs_sqs_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs_ucp_jobs_queue_url,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self.jobs_consumer = SqsConsumerManager(
            consumer=jobs_sqs_consumer,
            queue_name="ucp-jobs.fifo",
            handler=job_dispatcher.dispatch,
        )

    async def dispose(self) -> None:
        if self.db_provider:
            await self.db_provider.close()
