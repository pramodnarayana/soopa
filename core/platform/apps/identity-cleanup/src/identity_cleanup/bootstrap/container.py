import structlog
from database.provider import DatabaseProvider
from identity.adapters.outbound.database.postgres_identity_outbox_cleanup_repository import (
    SqlAlchemyIdentityOutboxCleanupRepository,
)
from identity.domain.constants import IdentityJobName
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from identity_cleanup.adapters.inbound.jobs.identity_outbox_cleanup_job import (
    IdentityOutboxCleanupJobHandler,
)
from identity_cleanup.config.settings import AppSettings

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the Identity Cleanup Worker."""

    def __init__(self, settings: AppSettings) -> None:
        self.db_provider = DatabaseProvider.from_url(settings.database_url)
        self.session_factory = self.db_provider.session_factory

        self.sqs_jobs_queue_url = settings.sqs_identity_jobs_queue_url
        self.aws_region = settings.aws_region
        self.aws_endpoint_url: str | None = settings.aws_endpoint_url

        self.jobs_consumer: SqsConsumerManager | None = None
        self.outbox_cleanup_job_handler: IdentityOutboxCleanupJobHandler | None = None

    def wire(self) -> None:
        self._wire_scheduled_jobs()
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(self) -> None:
        outbox_cleanup_repo = SqlAlchemyIdentityOutboxCleanupRepository(self.session_factory)
        outbox_cleaner_use_case = OutboxCleanerUseCase(outbox_cleanup_repo)
        self.outbox_cleanup_job_handler = IdentityOutboxCleanupJobHandler(outbox_cleaner_use_case)

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def outbox_cleanup_handler(message: JsonDict) -> None:
            if self.outbox_cleanup_job_handler:
                await self.outbox_cleanup_job_handler.execute()

        job_dispatcher.subscribe(
            IdentityJobName.IDENTITY_OUTBOX_CLEANUP.value,
            outbox_cleanup_handler,
        )

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
        await self.db_provider.close()
