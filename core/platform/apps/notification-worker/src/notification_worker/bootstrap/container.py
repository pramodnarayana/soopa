import structlog
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification_worker.adapters.inbound.workers.email_channel_dispatcher import (
    EmailChannelDispatcher,
)
from notification_worker.adapters.inbound.workers.notification_event_dispatcher import (
    NotificationEventDispatcher,
)

logger = structlog.get_logger(__name__)


class WorkerContainer(containers.DeclarativeContainer):
    """
    IoC container for the Notification Worker app.
    """

    config = providers.Configuration()

    notification_package = providers.Container(
        NotificationContainer,
        config=config,
    )

    outbox_publisher = providers.Singleton(
        AwsSnsPublisher,
        sns_topic_arn=config.sns_topic_arn,
    )

    outbox_processor = providers.Singleton(
        OutboxProcessorUseCase,
        repository=notification_package.outbox_repository,
        publisher=outbox_publisher,
        worker_id="notification_worker",
    )

    outbox_listener = providers.Singleton(
        PostgresOutboxRelay,
        processor=outbox_processor,
        database_url=config.database_url,
        listen_channel="notification_outbox_channel",
    )

    cleanup_worker = providers.Singleton(
        NotificationOutboxSweeperJobHandler,
        use_case=notification_package.outbox_sweeper_use_case(
            publisher=outbox_publisher,
        ),
    )

    notification_dispatcher = providers.Singleton(
        NotificationEventDispatcher,
        notification_compiler=notification_package.notification_compiler,
        cleanup_job_handler=cleanup_worker,
    )

    consumer_worker = providers.Singleton(
        SqsConsumerManager,
        queue_name="PriorityNotificationsQueue",
        endpoint_url=config.aws_endpoint_url,
        handler=notification_dispatcher.provided.dispatch_raw,
    )

    email_dispatcher = providers.Singleton(
        EmailChannelDispatcher,
        email_strategy=notification_package.email_strategy,
    )

    email_worker = providers.Singleton(
        SqsConsumerManager,
        queue_name="email-delivery.fifo",
        endpoint_url=config.aws_endpoint_url,
        handler=email_dispatcher.provided.dispatch_raw,
    )
