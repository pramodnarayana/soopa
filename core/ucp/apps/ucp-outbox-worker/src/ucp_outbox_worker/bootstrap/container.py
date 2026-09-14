import structlog
from database.provider import DatabaseProvider
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.config.settings import AppSettings
from ucp.domain.constants import UcpJobName

from ucp_outbox_worker.adapters.inbound.jobs.ucp_outbox_sweeper_job import (
    UcpOutboxSweeperJobHandler,
)

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the UCP Outbox Worker."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db_provider = DatabaseProvider.from_url(self.settings.database_url)
        self.session_factory = self.db_provider.session_factory

        self.outbox_relay: PostgresOutboxRelay | None = None
        self.jobs_consumer: SqsConsumerManager | None = None
        self.sweeper_job_handler: UcpOutboxSweeperJobHandler | None = None

    def wire(self) -> None:
        outbox_repo = PostgresOutboxRepository(self.session_factory)
        outbox_pub = AwsSnsPublisher(
            topic_arn=self.settings.sns_tenant_events_topic_arn,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self._wire_scheduled_jobs(outbox_repo, outbox_pub)
        self._wire_outbox_relay(outbox_repo, outbox_pub)
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(
        self, outbox_repo: PostgresOutboxRepository, outbox_pub: AwsSnsPublisher
    ) -> None:
        sweeper_use_case = OutboxSweeperUseCase(outbox_repo, outbox_pub)
        self.sweeper_job_handler = UcpOutboxSweeperJobHandler(sweeper_use_case)

    def _wire_outbox_relay(
        self, outbox_repo: PostgresOutboxRepository, outbox_pub: AwsSnsPublisher
    ) -> None:
        outbox_processor = OutboxProcessorUseCase(
            repository=outbox_repo,
            publisher=outbox_pub,
        )
        self.outbox_relay = PostgresOutboxRelay(
            processor=outbox_processor,
            database_url=self.settings.database_url,
            listen_channel="ucp_outbox_wakeup",
        )

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def sweep_handler(message: JsonDict) -> None:
            if self.sweeper_job_handler:
                await self.sweeper_job_handler.execute()

        job_dispatcher.subscribe(UcpJobName.UCP_OUTBOX_SWEEPER.value, sweep_handler)

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
