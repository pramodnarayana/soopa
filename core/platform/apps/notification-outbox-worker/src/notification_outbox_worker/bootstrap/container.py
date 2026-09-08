import structlog
from dependency_injector import containers, providers
from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.bootstrap.container import Container as NotificationContainer
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher

logger = structlog.get_logger(__name__)


class WorkerContainer(containers.DeclarativeContainer):
    """
    IoC container for the Notification Outbox Worker app.
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
        worker_id="notification_outbox_worker",
    )

    outbox_listener = providers.Singleton(
        PostgresOutboxRelay,
        processor=outbox_processor,
        database_url=config.database_url,
        listen_channel="notification_outbox_channel",
    )
