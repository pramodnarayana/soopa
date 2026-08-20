import structlog
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer

from notification_worker.adapters.inbound.consumer import NotificationConsumerWorker
from notification_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJob,
)
from notification_worker.adapters.inbound.notification_outbox_relay import NotificationOutboxRelay
from notification_worker.adapters.inbound.postgres_listener import PostgresNotificationListener

logger = structlog.get_logger(__name__)


class WorkerContainer(containers.DeclarativeContainer):
    """
    IoC container for the Notification Worker app.
    It wraps the domain package container to get use cases and repositories,
    and constructs the worker execution boundaries.
    """

    config = providers.Configuration()

    # Import the domain package container
    notification_package = providers.Container(
        NotificationContainer,
        config=config,
    )

    outbox_listener = providers.Singleton(
        NotificationOutboxRelay,
        processor=notification_package.outbox_processor,
        database_url=config.database_url,
    )

    cleanup_worker = providers.Singleton(
        NotificationOutboxSweeperJob,
        use_case=notification_package.sweep_outbox_use_case,
    )

    postgres_listener = providers.Singleton(
        PostgresNotificationListener,
        database_url=config.database_url,
        stream_manager=notification_package.stream_manager,
    )

    consumer_worker = providers.Singleton(
        NotificationConsumerWorker,
        dispatch_use_case=notification_package.dispatch_use_case,
        cleanup_job_handler=cleanup_worker,
    )
