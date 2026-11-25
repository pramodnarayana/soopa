import structlog
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from pubsub.domain.dtos import TopicSubscriptionSpec
from pubsub.domain.enums import PlatformTopicName
from pubsub.provider import PubSubProvider

from notification_channel_worker.adapters.inbound.workers.email_channel_dispatcher import (
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

    email_channel_consumer = providers.Callable(
        PubSubProvider.create_consumer_manager,
        source_uri=config.sqs_email_channel_queue_url,
        handler=email_dispatcher.provided.dispatch_raw,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
        session_factory=notification_package.session_factory,
        database_url=config.database_url,
        subscribe_topics=(
            TopicSubscriptionSpec(
                topic_name=PlatformTopicName.PLATFORM_EVENTS.value,
                event_types=("channel.email.", "email."),
            ),
        ),
    )
