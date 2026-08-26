import structlog
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

from notification_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification_worker.adapters.inbound.workers.email_channel_sqs_consumer import (
    EmailChannelSqsConsumer,
)
from notification_worker.adapters.inbound.workers.notification_event_sqs_consumer import (
    NotificationEventSqsConsumer,
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

    priority_queue_consumer = providers.Singleton(
        AwsSqsConsumer,
        queue_name="PriorityNotificationsQueue",
        endpoint_url=config.aws_endpoint_url,
    )

    consumer_worker = providers.Singleton(
        NotificationEventSqsConsumer,
        consumer=priority_queue_consumer,
        notification_compiler=notification_package.notification_compiler,
        cleanup_job_handler=cleanup_worker,
    )

    email_delivery_queue_consumer = providers.Singleton(
        AwsSqsConsumer,
        queue_name="email-delivery.fifo",
        endpoint_url=config.aws_endpoint_url,
    )

    email_worker = providers.Singleton(
        EmailChannelSqsConsumer,
        consumer=email_delivery_queue_consumer,
        email_strategy=notification_package.email_strategy,
    )
