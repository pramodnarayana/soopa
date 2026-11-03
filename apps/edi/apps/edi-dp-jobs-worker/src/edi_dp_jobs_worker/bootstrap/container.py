import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.bootstrap.publisher_factory import create_edi_pipeline_publisher
from edi.domain.constants import EdiConstants
from edi.domain.enums import EdiJobName, EdiOutboxSource
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict

from edi_dp_jobs_worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_dp_jobs_worker.adapters.inbound.jobs.edi_data_plane_outbox_sweeper_job import (
    EdiDataPlaneOutboxSweeperJobHandler,
)
from edi_dp_jobs_worker.adapters.inbound.jobs.edi_data_retention_cleanup_job import (
    EdiDataRetentionCleanupJobHandler,
)
from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_retention_cleanup_repository import (
    SqlAlchemyEdiDataRetentionCleanupRepository,
)
from edi_dp_jobs_worker.application.use_cases.edi_data_retention_cleanup_use_case import (
    EdiDataRetentionCleanupUseCase,
)
from edi_dp_jobs_worker.settings import get_settings

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the EDI Data Plane Jobs Worker."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db_router = DatabaseRouter(
            global_db_url=self.settings.database.global_url,
            shard_overrides=self.settings.database.shard_overrides,
        )

        self.dp_manager: SqsConsumerManager | None = None
        self.dp_cleanup_job_handler: EdiDataPlaneOutboxCleanupJobHandler | None = None
        self.retention_cleanup_job_handler: EdiDataRetentionCleanupJobHandler | None = None
        self.dp_sweeper_job_handler: EdiDataPlaneOutboxSweeperJobHandler | None = None

    def wire(self) -> None:
        self._wire_scheduled_jobs()
        self._wire_jobs_consumers()

    def _wire_scheduled_jobs(self) -> None:
        sharded_outbox_repo = SqlAlchemyShardedOutboxRepository(
            db_router=self.db_router,
            model_cls=DataPlaneOutbox,
            app_slug=EdiConstants.EDI_APP_SLUG.value,
            source=EdiOutboxSource.EDI_DATA_PLANE.value,
            min_pending_age_seconds=60,
        )
        self.dp_cleanup_job_handler = EdiDataPlaneOutboxCleanupJobHandler(
            OutboxCleanerUseCase(sharded_outbox_repo)
        )

        retention_cleanup_repo = SqlAlchemyEdiDataRetentionCleanupRepository(
            db_router=self.db_router
        )
        self.retention_cleanup_job_handler = EdiDataRetentionCleanupJobHandler(
            EdiDataRetentionCleanupUseCase(retention_cleanup_repo)
        )

        publisher = create_edi_pipeline_publisher(
            compute_queue_url=self.settings.sqs.compute_queue_url,
            orchestrator_queue_url=self.settings.sqs.orchestrator_queue_url,
            deliver_queue_url=self.settings.sqs.deliver_queue_url,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )

        self.dp_sweeper_job_handler = EdiDataPlaneOutboxSweeperJobHandler(
            OutboxSweeperUseCase(repository=sharded_outbox_repo, publisher=publisher)
        )

    def _wire_jobs_consumers(self) -> None:
        dp_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def dp_cleanup_handler(msg: JsonDict) -> None:
            if self.dp_cleanup_job_handler:
                await self.dp_cleanup_job_handler.execute()

        async def retention_cleanup_handler(msg: JsonDict) -> None:
            if self.retention_cleanup_job_handler:
                await self.retention_cleanup_job_handler.execute()

        async def dp_sweeper_handler(msg: JsonDict) -> None:
            if self.dp_sweeper_job_handler:
                await self.dp_sweeper_job_handler.execute()

        dp_dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value, dp_cleanup_handler)
        dp_dispatcher.subscribe(
            EdiJobName.EDI_DATA_RETENTION_CLEANUP.value, retention_cleanup_handler
        )
        dp_dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value, dp_sweeper_handler)

        self.dp_manager = PubSubProvider.create_consumer_manager(
            queue_url=self.settings.sqs.data_plane_jobs_queue_url,
            handler=dp_dispatcher.dispatch,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )

    async def start(self) -> None:
        if self.dp_manager:
            self.dp_manager.start()

    async def dispose(self) -> None:
        try:
            if self.dp_manager:
                await self.dp_manager.stop()
        finally:
            if self.db_router:
                await self.db_router.close_all()
