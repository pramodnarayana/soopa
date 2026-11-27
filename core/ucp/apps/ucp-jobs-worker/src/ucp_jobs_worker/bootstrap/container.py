import structlog
from database.provider import DatabaseProvider
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_relay_port import OutboxRelayPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.ports.consumer_manager_port import ConsumerManagerPort
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict
from ucp.adapters.outbound.database.ucp_audit_log_cleanup_repository import (
    SqlAlchemyUcpAuditLogCleanupRepository,
)
from ucp.adapters.outbound.database.ucp_idempotency_cleanup_repository import (
    SqlAlchemyUcpIdempotencyCleanupRepository,
)
from ucp.application.use_cases.ucp_audit_log_cleanup_use_case import UcpAuditLogCleanupUseCase
from ucp.application.use_cases.ucp_idempotency_cleanup_use_case import UcpIdempotencyCleanupUseCase
from ucp.config.settings import AppSettings
from ucp.domain.constants import UcpJobName, UcpOutboxSource
from ucp_models.events import UcpOutbox

from ucp_jobs_worker.adapters.inbound.jobs.ucp_audit_log_cleanup_job import (
    UcpAuditLogCleanupJobHandler,
)
from ucp_jobs_worker.adapters.inbound.jobs.ucp_idempotency_cleanup_job import (
    UcpIdempotencyCleanupJobHandler,
)
from ucp_jobs_worker.adapters.inbound.jobs.ucp_outbox_cleanup_job import UcpOutboxCleanupJobHandler
from ucp_jobs_worker.adapters.inbound.jobs.ucp_outbox_sweeper_job import (
    UcpOutboxSweeperJobHandler,
)
from ucp_jobs_worker.constants import UcpCleanupJobName

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the UCP Jobs Worker."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db_provider = DatabaseProvider.from_url(self.settings.database_url)
        self.session_factory = self.db_provider.session_factory

        self.outbox_relay: OutboxRelayPort | None = None
        self.jobs_consumer: ConsumerManagerPort | None = None

        self.sweeper_job_handler: UcpOutboxSweeperJobHandler | None = None
        self.outbox_cleanup_job_handler: UcpOutboxCleanupJobHandler | None = None
        self.idemp_cleanup_job_handler: UcpIdempotencyCleanupJobHandler | None = None
        self.audit_cleanup_job_handler: UcpAuditLogCleanupJobHandler | None = None

    def wire(self) -> None:
        outbox_repo = SqlAlchemyGlobalOutboxRepository(
            session_factory=self.session_factory,
            model_cls=UcpOutbox,
            source=UcpOutboxSource.UCP.value,
        )
        outbox_pub = PubSubProvider.create_outbox_publisher(
            destination_uri=self.settings.sns_tenant_events_topic_arn,
            endpoint_url=self.settings.aws_endpoint_url,
            region_name=self.settings.aws_region,
            transport=self.settings.pubsub_transport,
            session_factory=self.session_factory,
            database_url=self.settings.database_url,
        )
        self._wire_scheduled_jobs(outbox_repo, outbox_repo, outbox_pub)
        self._wire_outbox_relay(outbox_repo, outbox_pub)
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(
        self,
        outbox_repo: OutboxRepositoryPort,
        outbox_cleanup_repo: OutboxCleanupRepositoryPort,
        outbox_pub: OutboxPublisherPort,
    ) -> None:
        sweeper_use_case = OutboxSweeperUseCase(outbox_repo, outbox_pub)
        self.sweeper_job_handler = UcpOutboxSweeperJobHandler(sweeper_use_case)

        idemp_cleanup_repo = SqlAlchemyUcpIdempotencyCleanupRepository(self.session_factory)
        audit_cleanup_repo = SqlAlchemyUcpAuditLogCleanupRepository(self.session_factory)

        outbox_cleaner_use_case = OutboxCleanerUseCase(outbox_cleanup_repo)
        idemp_cleanup_use_case = UcpIdempotencyCleanupUseCase(idemp_cleanup_repo)
        audit_cleanup_use_case = UcpAuditLogCleanupUseCase(audit_cleanup_repo)

        self.outbox_cleanup_job_handler = UcpOutboxCleanupJobHandler(outbox_cleaner_use_case)
        self.idemp_cleanup_job_handler = UcpIdempotencyCleanupJobHandler(idemp_cleanup_use_case)
        self.audit_cleanup_job_handler = UcpAuditLogCleanupJobHandler(audit_cleanup_use_case)

    def _wire_outbox_relay(
        self, outbox_repo: OutboxRepositoryPort, outbox_pub: OutboxPublisherPort
    ) -> None:
        outbox_processor = OutboxProcessorUseCase(
            repository=outbox_repo,
            publisher=outbox_pub,
        )
        self.outbox_relay = OutboxDrainRelay(
            processor=outbox_processor,
            relay_name=UcpOutboxSource.UCP.value,
        )

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def sweep_handler(message: JsonDict) -> None:
            if self.sweeper_job_handler:
                await self.sweeper_job_handler.execute()

        async def outbox_cleanup_handler(message: JsonDict) -> None:
            if self.outbox_cleanup_job_handler:
                await self.outbox_cleanup_job_handler.execute()

        async def idemp_cleanup_handler(message: JsonDict) -> None:
            if self.idemp_cleanup_job_handler:
                await self.idemp_cleanup_job_handler.execute()

        async def audit_cleanup_handler(message: JsonDict) -> None:
            if self.audit_cleanup_job_handler:
                await self.audit_cleanup_job_handler.execute()

        job_dispatcher.subscribe(UcpJobName.UCP_OUTBOX_SWEEPER.value, sweep_handler)
        job_dispatcher.subscribe(UcpCleanupJobName.UCP_OUTBOX_CLEANUP.value, outbox_cleanup_handler)
        job_dispatcher.subscribe(
            UcpCleanupJobName.UCP_IDEMPOTENCY_CLEANUP.value, idemp_cleanup_handler
        )
        job_dispatcher.subscribe(
            UcpCleanupJobName.UCP_AUDIT_LOG_CLEANUP.value, audit_cleanup_handler
        )

        self.jobs_consumer = PubSubProvider.create_consumer_manager(
            source_uri=self.settings.sqs_ucp_jobs_queue_url,
            handler=job_dispatcher.dispatch,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
            transport=self.settings.pubsub_transport,
            session_factory=self.session_factory,
            database_url=self.settings.database_url,
        )

    async def dispose(self) -> None:
        if self.db_provider:
            await self.db_provider.close()
