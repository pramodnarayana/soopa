import os

import structlog
from database.provider import DatabaseProvider
from identity.adapters.outbound.database.postgres_identity_outbox_repository import (
    PostgresIdentityOutboxRepository,
)
from identity.domain.constants import IdentityJobName
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from identity_outbox_worker.adapters.inbound.jobs.identity_outbox_sweeper_job import (
    IdentityOutboxSweeperJobHandler,
)

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the Identity Outbox Worker."""

    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL", "")
        self.db_provider = DatabaseProvider.from_url(self.database_url)
        self.session_factory = self.db_provider.session_factory

        self.sns_identity_events_topic_arn = os.environ.get("SNS_IDENTITY_EVENTS_TOPIC_ARN", "")
        self.aws_endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL")
        self.sqs_jobs_queue_url = os.environ.get("SQS_IDENTITY_JOBS_QUEUE_URL", "")
        self.aws_region = os.environ.get("AWS_REGION", "us-east-1")

        self.outbox_relay: PostgresOutboxRelay | None = None
        self.jobs_consumer: SqsConsumerManager | None = None
        self.sweeper_job_handler: IdentityOutboxSweeperJobHandler | None = None

    def wire(self) -> None:
        outbox_repo = PostgresIdentityOutboxRepository(self.session_factory)
        outbox_pub = AwsSnsPublisher(
            topic_arn=self.sns_identity_events_topic_arn,
            endpoint_url=self.aws_endpoint_url,
        )
        self._wire_scheduled_jobs(outbox_repo, outbox_pub)
        self._wire_outbox_relay(outbox_repo, outbox_pub)
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(
        self, outbox_repo: PostgresIdentityOutboxRepository, outbox_pub: AwsSnsPublisher
    ) -> None:
        sweeper_use_case = OutboxSweeperUseCase(outbox_repo, outbox_pub)
        self.sweeper_job_handler = IdentityOutboxSweeperJobHandler(sweeper_use_case)

    def _wire_outbox_relay(
        self, outbox_repo: PostgresIdentityOutboxRepository, outbox_pub: AwsSnsPublisher
    ) -> None:
        outbox_processor = OutboxProcessorUseCase(
            repository=outbox_repo,
            publisher=outbox_pub,
        )
        self.outbox_relay = PostgresOutboxRelay(
            processor=outbox_processor,
            database_url=self.database_url,
            listen_channel="identity_outbox_wakeup",
        )

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def sweep_handler(message: JsonDict) -> None:
            if self.sweeper_job_handler:
                await self.sweeper_job_handler.execute()

        job_dispatcher.subscribe(IdentityJobName.IDENTITY_OUTBOX_SWEEPER.value, sweep_handler)

        jobs_sqs_consumer = AwsSqsConsumer(
            queue_url=self.sqs_jobs_queue_url,
            region_name=self.aws_region,
            endpoint_url=self.aws_endpoint_url,
        )
        self.jobs_consumer = SqsConsumerManager(
            consumer=jobs_sqs_consumer,
            queue_name="identity-jobs.fifo",
            handler=job_dispatcher.dispatch,
        )

    async def dispose(self) -> None:
        if self.db_provider:
            await self.db_provider.close()
