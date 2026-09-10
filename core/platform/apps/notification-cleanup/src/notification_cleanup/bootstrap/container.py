import structlog
from database.provider import DatabaseProvider
from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.domain.constants import NotificationCleanupJobName
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from notification_cleanup.adapters.inbound.jobs.notification_outbox_cleanup_job import (
    NotificationOutboxCleanupJobHandler,
)
from notification_cleanup.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification_cleanup.adapters.outbound.database.postgres_notification_outbox_cleanup_repository import (
    SqlAlchemyNotificationOutboxCleanupRepository,
)
from notification_cleanup.config.settings import AppSettings

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the Notification Cleanup Worker."""

    def __init__(self, settings: AppSettings) -> None:
        self.db_provider = DatabaseProvider.from_url(settings.database_url)
        self.session_factory = self.db_provider.session_factory

        self.sqs_jobs_queue_url = settings.sqs_notification_jobs_queue_url
        self.aws_region = settings.aws_region
        self.aws_endpoint_url: str | None = settings.aws_endpoint_url
        self.sns_topic_arn: str = settings.sns_topic_arn

        self.jobs_consumer: SqsConsumerManager | None = None
        self.outbox_cleanup_job_handler: NotificationOutboxCleanupJobHandler | None = None
        self.outbox_sweeper_job_handler: NotificationOutboxSweeperJobHandler | None = None

    def wire(self) -> None:
        self._wire_scheduled_jobs()
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(self) -> None:
        outbox_cleanup_repo = SqlAlchemyNotificationOutboxCleanupRepository(self.session_factory)
        outbox_cleaner_use_case = OutboxCleanerUseCase(outbox_cleanup_repo)
        self.outbox_cleanup_job_handler = NotificationOutboxCleanupJobHandler(
            outbox_cleaner_use_case
        )

        outbox_repo = SqlAlchemyNotificationOutboxRepository(self.session_factory)
        outbox_publisher = AwsSnsPublisher(
            topic_arn=self.sns_topic_arn,
            region_name=self.aws_region,
            endpoint_url=self.aws_endpoint_url,
        )
        outbox_sweeper_use_case = OutboxSweeperUseCase(
            repository=outbox_repo,
            publisher=outbox_publisher,
        )
        self.outbox_sweeper_job_handler = NotificationOutboxSweeperJobHandler(
            use_case=outbox_sweeper_use_case
        )

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def outbox_cleanup_handler(message: JsonDict) -> None:
            if self.outbox_cleanup_job_handler:
                await self.outbox_cleanup_job_handler.execute()

        async def outbox_sweeper_handler(message: JsonDict) -> None:
            if self.outbox_sweeper_job_handler:
                await self.outbox_sweeper_job_handler.execute()

        job_dispatcher.subscribe(
            NotificationCleanupJobName.NOTIFICATION_OUTBOX_CLEANUP.value,
            outbox_cleanup_handler,
        )
        job_dispatcher.subscribe(
            NotificationCleanupJobName.NOTIFICATION_OUTBOX_SWEEPER.value,
            outbox_sweeper_handler,
        )

        jobs_sqs_consumer = AwsSqsConsumer(
            queue_url=self.sqs_jobs_queue_url,
            region_name=self.aws_region,
            endpoint_url=self.aws_endpoint_url,
        )
        self.jobs_consumer = SqsConsumerManager(
            consumer=jobs_sqs_consumer,
            queue_name="notification-jobs.fifo",
            handler=job_dispatcher.dispatch,
        )

    async def dispose(self) -> None:
        await self.db_provider.close()
