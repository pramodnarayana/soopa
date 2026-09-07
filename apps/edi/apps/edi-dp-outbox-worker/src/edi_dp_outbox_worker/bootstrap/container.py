import structlog
from database.router import DatabaseRouter
from edi.config.settings import get_settings
from edi.domain.enums import EdiJobName
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from edi_dp_outbox_worker.adapters.inbound.jobs.edi_data_plane_outbox_sweeper_job import (
    EdiDataPlaneOutboxSweeperJobHandler,
)
from edi_dp_outbox_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
)

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the EDI Data Plane Outbox Worker."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db_router = DatabaseRouter(global_db_url=self.settings.database.global_url)

        self.dp_manager: SqsConsumerManager | None = None
        self.dp_sweeper_job_handler: EdiDataPlaneOutboxSweeperJobHandler | None = None

    def wire(self) -> None:
        dp_outbox_repo = PostgresEdiDataPlaneOutboxRepository(db_router=self.db_router)

        dp_outbox_publisher = AwsSqsPublisher(
            queue_url=self.settings.sqs.data_plane_jobs_queue_url,
            endpoint_url=self.settings.aws.endpoint_url,
            region_name=self.settings.aws.resolved_region,
        )

        self._wire_scheduled_jobs(dp_outbox_repo, dp_outbox_publisher)
        self._wire_jobs_consumers()

    def _wire_scheduled_jobs(
        self,
        dp_repo: PostgresEdiDataPlaneOutboxRepository,
        dp_pub: AwsSqsPublisher,
    ) -> None:
        dp_sweeper_use_case = OutboxSweeperUseCase(dp_repo, dp_pub)
        self.dp_sweeper_job_handler = EdiDataPlaneOutboxSweeperJobHandler(dp_sweeper_use_case)

    def _wire_jobs_consumers(self) -> None:
        dp_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def dp_sweeper_handler(msg: JsonDict) -> None:
            if self.dp_sweeper_job_handler:
                await self.dp_sweeper_job_handler.execute()

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
        if self.dp_manager:
            await self.dp_manager.stop()
        if self.db_router:
            await self.db_router.close_all()
