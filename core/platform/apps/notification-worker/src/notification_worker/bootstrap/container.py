import structlog
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from pubsub.provider import PubSubProvider

from notification_worker.adapters.inbound.workers.notification_event_dispatcher import (
    NotificationEventDispatcher,
)

logger = structlog.get_logger(__name__)

# NOTE: Outbox cleanup (deletion of old PROCESSED records) and Outbox Sweeping
# are handled by the dedicated notification-cleanup worker container.
# Realtime Outbox Relaying is handled by the notification-outbox-worker.
# Email Delivery is handled by the notification-email-worker.


class WorkerContainer(containers.DeclarativeContainer):
    """
    IoC container for the Notification Worker app (Compiler Worker).
    """

    config = providers.Configuration()

    notification_package = providers.Container(
        NotificationContainer,
        config=config,
    )

    notification_dispatcher = providers.Singleton(
        NotificationEventDispatcher,
        notification_compiler=notification_package.notification_compiler,
    )

    consumer_worker = providers.Callable(
        PubSubProvider.create_consumer_manager,
        source_uri=config.sqs_notification_queue_url,
        handler=notification_dispatcher.provided.dispatch_raw,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
    )
