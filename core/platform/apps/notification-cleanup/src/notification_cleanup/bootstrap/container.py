import os

import structlog
from database.provider import DatabaseProvider
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from notification_cleanup.adapters.inbound.jobs.notification_outbox_cleanup_job import (
    NotificationOutboxCleanupJobHandler,
)
from notification_cleanup.adapters.outbound.database.postgres_notification_outbox_cleanup_repository import (
    SqlAlchemyNotificationOutboxCleanupRepository,
)
from notification_cleanup.constants import NotificationCleanupJobName

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the Notification Cleanup Worker."""

    def __init__(self) -> None:
        database_url = os.environ.get("DATABASE_URL", "")
        self.db_provider = DatabaseProvider.from_url(database_url)
        self.session_factory = self.db_provider.session_factory

        self.sqs_jobs_queue_url = os.environ.get("SQS_NOTIFICATION_JOBS_QUEUE_URL", "")
        self.aws_region = os.environ.get("AWS_REGION", "us-east-1")
        self.aws_endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL")

        self.jobs_consumer: SqsConsumerManager | None = None
        self.outbox_cleanup_job_handler: NotificationOutboxCleanupJobHandler | None = None

    def wire(self) -> None:
        self._wire_scheduled_jobs()
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(self) -> None:
        outbox_cleanup_repo = SqlAlchemyNotificationOutboxCleanupRepository(self.session_factory)
        outbox_cleaner_use_case = OutboxCleanerUseCase(outbox_cleanup_repo)
        self.outbox_cleanup_job_handler = NotificationOutboxCleanupJobHandler(
            outbox_cleaner_use_case
        )

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def outbox_cleanup_handler(message: JsonDict) -> None:
            if self.outbox_cleanup_job_handler:
                await self.outbox_cleanup_job_handler.execute()

        job_dispatcher.subscribe(
            NotificationCleanupJobName.NOTIFICATION_OUTBOX_CLEANUP.value,
            outbox_cleanup_handler,
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
