import structlog
from dependency_injector import containers, providers
from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.bootstrap.container import Container as NotificationContainer
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
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
        topic_arn=config.sns_topic_arn,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )

    outbox_repository = providers.Factory(
        SqlAlchemyNotificationOutboxRepository,
        session_factory=notification_package.session_factory,
    )

    outbox_processor = providers.Singleton(
        OutboxProcessorUseCase,
        repository=outbox_repository,
        publisher=outbox_publisher,
        worker_id="notification_worker",
    )

    outbox_listener = providers.Singleton(
        PostgresOutboxRelay,
        processor=outbox_processor,
        database_url=config.database_url,
        listen_channel="notification_outbox_channel",
    )

    outbox_sweeper = providers.Singleton(
        OutboxSweeperUseCase,
        repository=outbox_repository,
        publisher=outbox_publisher,
    )

    cleanup_worker = providers.Singleton(
        NotificationOutboxSweeperJobHandler,
        use_case=outbox_sweeper,
    )

    notification_dispatcher = providers.Singleton(
        NotificationEventDispatcher,
        notification_compiler=notification_package.notification_compiler,
        cleanup_job_handler=cleanup_worker,
    )

    priority_queue_consumer = providers.Singleton(
        AwsSqsConsumer,
        queue_url=config.priority_queue_url,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )

    consumer_worker = providers.Singleton(
        SqsConsumerManager,
        consumer=priority_queue_consumer,
        queue_name="edi-priority-notifications.fifo",
        handler=notification_dispatcher.provided.dispatch_raw,
    )

    email_dispatcher = providers.Singleton(
        EmailChannelDispatcher,
        email_strategy=notification_package.email_strategy,
    )

    email_delivery_consumer = providers.Singleton(
        AwsSqsConsumer,
        queue_url=config.email_delivery_queue_url,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )

    email_worker = providers.Singleton(
        SqsConsumerManager,
        consumer=email_delivery_consumer,
        queue_name="email-delivery.fifo",
        handler=email_dispatcher.provided.dispatch_raw,
    )
