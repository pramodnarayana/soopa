import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.pubsub.routing_sqs_publisher import RoutingSqsPublisher
from edi.config.settings import get_settings
from edi.domain.enums import EdiJobName, PipelineEventType
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
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
from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_plane_outbox_sweeper_repository import (
    SqlAlchemyEdiDataPlaneOutboxSweeperRepository,
)
from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_retention_cleanup_repository import (
    SqlAlchemyEdiDataRetentionCleanupRepository,
)
from edi_dp_jobs_worker.application.use_cases.edi_data_plane_outbox_sweeper_use_case import (
    EdiDataPlaneOutboxSweeperUseCase,
)
from edi_dp_jobs_worker.application.use_cases.edi_data_retention_cleanup_use_case import (
    EdiDataRetentionCleanupUseCase,
)

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
        dp_cleanup_repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=self.db_router)
        self.dp_cleanup_job_handler = EdiDataPlaneOutboxCleanupJobHandler(
            OutboxCleanerUseCase(dp_cleanup_repo)
        )

        retention_cleanup_repo = SqlAlchemyEdiDataRetentionCleanupRepository(
            db_router=self.db_router
        )
        self.retention_cleanup_job_handler = EdiDataRetentionCleanupJobHandler(
            EdiDataRetentionCleanupUseCase(retention_cleanup_repo)
        )

        sweeper_repo = SqlAlchemyEdiDataPlaneOutboxSweeperRepository(db_router=self.db_router)
        routing_map = {
            PipelineEventType.TRANSFORMATION_REQUESTED.value: self.settings.sqs.compute_queue_url,
            PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value: self.settings.sqs.orchestrator_queue_url,
            PipelineEventType.TRANSFORMATION_SUCCESSFUL.value: self.settings.sqs.orchestrator_queue_url,
            PipelineEventType.EXECUTE_DELIVERY_COMMAND.value: self.settings.sqs.deliver_queue_url,
            PipelineEventType.DELIVERY_REQUESTED.value: self.settings.sqs.deliver_queue_url,
        }
        publisher = RoutingSqsPublisher(
            event_type_to_queue_url=routing_map,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )
        self.dp_sweeper_job_handler = EdiDataPlaneOutboxSweeperJobHandler(
            EdiDataPlaneOutboxSweeperUseCase(repository=sweeper_repo, publisher=publisher)
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

        dp_sqs_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs.data_plane_jobs_queue_url,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )
        self.dp_manager = SqsConsumerManager(
            consumer=dp_sqs_consumer,
            queue_name=self.settings.sqs.data_plane_jobs_queue_url.rsplit("/", 1)[-1],
            handler=dp_dispatcher.dispatch,
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
