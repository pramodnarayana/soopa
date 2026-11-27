import structlog
from database.models.notifications import NotificationOutbox
from dependency_injector import containers, providers
from notification.bootstrap.container import Container as NotificationContainer
from notification.domain.constants import (
    NotificationCleanupJobName,
    NotificationOutboxSource,
)
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.provider import PubSubProvider
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

    outbox_publisher = providers.Callable(
        PubSubProvider.create_outbox_publisher,
        destination_uri=config.sns_topic_arn,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
        transport=config.pubsub_transport,
        session_factory=notification_package.session_factory,
        database_url=config.database_url,
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

    outbox_relay = providers.Singleton(
        OutboxDrainRelay,
        processor=outbox_processor,
        relay_name=NotificationOutboxSource.NOTIFICATION.value,
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

    jobs_consumer = providers.Callable(
        PubSubProvider.create_consumer_manager,
        source_uri=config.sqs_notification_jobs_queue_url,
        handler=job_dispatcher.provided.dispatch,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
        transport=config.pubsub_transport,
        session_factory=notification_package.session_factory,
        database_url=config.database_url,
    )
