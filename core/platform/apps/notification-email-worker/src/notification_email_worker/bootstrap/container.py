import structlog
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_email_worker.adapters.inbound.workers.email_channel_dispatcher import (
    EmailChannelDispatcher,
)

logger = structlog.get_logger(__name__)


class WorkerContainer(containers.DeclarativeContainer):
    """
    IoC container for the Notification Email Worker app.
    """

    config = providers.Configuration()

    notification_package = providers.Container(
        NotificationContainer,
        config=config,
    )

    email_dispatcher = providers.Singleton(
        EmailChannelDispatcher,
        email_strategy=notification_package.email_strategy,
    )

    email_delivery_consumer = providers.Singleton(
        AwsSqsConsumer,
        queue_url=config.sqs_email_channel_queue_url,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )

    email_worker = providers.Singleton(
        SqsConsumerManager,
        consumer=email_delivery_consumer,
        queue_name="email-channel.fifo",
        handler=email_dispatcher.provided.dispatch_raw,
    )
