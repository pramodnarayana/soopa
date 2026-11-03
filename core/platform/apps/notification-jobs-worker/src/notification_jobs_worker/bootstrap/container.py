import structlog
from database.models.notifications import NotificationOutbox
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from notification.domain.constants import (
    NotificationCleanupJobName,
    NotificationOutboxChannel,
    NotificationOutboxSource,
)
from outbox.adapters.inbound.notify_outbox_relay import NotifyOutboxRelay
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from notification_jobs_worker.adapters.inbound.jobs.notification_outbox_cleanup_job import (
    NotificationOutboxCleanupJobHandler,
)
from notification_jobs_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)

logger = structlog.get_logger(__name__)


def init_job_dispatcher(
    cleanup_handler: NotificationOutboxCleanupJobHandler,
    sweeper_handler: NotificationOutboxSweeperJobHandler,
) -> MessageDispatcher:
    dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

    async def outbox_cleanup_handler(message: JsonDict) -> None:
        del message
        await cleanup_handler.execute()

    async def outbox_sweeper_handler(message: JsonDict) -> None:
        del message
        await sweeper_handler.execute()

    dispatcher.subscribe(
        NotificationCleanupJobName.NOTIFICATION_OUTBOX_CLEANUP.value, outbox_cleanup_handler
    )
    dispatcher.subscribe(
        NotificationCleanupJobName.NOTIFICATION_OUTBOX_SWEEPER.value, outbox_sweeper_handler
    )
    return dispatcher


class WorkerContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    notification_package = providers.Container(
        NotificationContainer,
        config=config,
    )

    outbox_publisher = providers.Singleton(
        AwsSnsPublisher,
        topic_arn=config.sns_topic_arn,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )

    outbox_repository = providers.Factory(
        SqlAlchemyGlobalOutboxRepository,
        session_factory=notification_package.session_factory,
        model_cls=NotificationOutbox,
        source=NotificationOutboxSource.NOTIFICATION.value,
    )

    outbox_processor = providers.Singleton(
        OutboxProcessorUseCase,
        repository=outbox_repository,
        publisher=outbox_publisher,
        worker_id="notification_jobs_worker",
    )

    outbox_listener = providers.Singleton(
        NotifyOutboxRelay,
        processor=outbox_processor,
        database_url=config.database_url,
        listen_channel=NotificationOutboxChannel.DELIVERY_WAKEUP.value,
    )

    outbox_cleaner_use_case = providers.Factory(
        OutboxCleanerUseCase,
        repository=outbox_repository,
    )

    outbox_cleanup_job_handler = providers.Factory(
        NotificationOutboxCleanupJobHandler,
        use_case=outbox_cleaner_use_case,
    )

    outbox_sweeper_use_case = providers.Factory(
        OutboxSweeperUseCase,
        repository=outbox_repository,
        publisher=outbox_publisher,
    )

    outbox_sweeper_job_handler = providers.Factory(
        NotificationOutboxSweeperJobHandler,
        use_case=outbox_sweeper_use_case,
    )

    job_dispatcher = providers.Factory(
        init_job_dispatcher,
        cleanup_handler=outbox_cleanup_job_handler,
        sweeper_handler=outbox_sweeper_job_handler,
    )

    jobs_sqs_consumer = providers.Factory(
        AwsSqsConsumer,
        queue_url=config.sqs_notification_jobs_queue_url,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )

    jobs_consumer = providers.Singleton(
        SqsConsumerManager,
        consumer=jobs_sqs_consumer,
        queue_name="notification-jobs.fifo",
        handler=job_dispatcher.provided.dispatch,
    )
