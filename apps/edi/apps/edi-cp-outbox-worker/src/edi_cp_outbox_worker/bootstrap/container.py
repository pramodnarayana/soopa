import structlog
from config_sync_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_repository import (
    PostgresEdiControlPlaneOutboxRepository,
)
from database.router import DatabaseRouter
from edi.config.settings import get_settings
from edi.domain.enums import EdiConstants, EdiJobName
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from edi_cp_outbox_worker.adapters.inbound.jobs.edi_control_plane_outbox_sweeper_job import (
    EdiControlPlaneOutboxSweeperJobHandler,
)

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the EDI Control Plane Worker."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db_router = DatabaseRouter(global_db_url=self.settings.database.global_url)

        self.cp_outbox_relay: PostgresOutboxRelay | None = None
        self.cp_manager: SqsConsumerManager | None = None

        self.cp_sweeper_job_handler: EdiControlPlaneOutboxSweeperJobHandler | None = None
        self.cp_outbox_publisher: AwsSnsPublisher | None = None

    def wire(self) -> None:
        cp_outbox_repo = PostgresEdiControlPlaneOutboxRepository(db_router=self.db_router)

        self.cp_outbox_publisher = AwsSnsPublisher(
            topic_arn=self.settings.aws.sns_topic_arn,
            endpoint_url=self.settings.aws.endpoint_url,
            region_name=self.settings.aws.default_region,
        )

        self._wire_scheduled_jobs(cp_outbox_repo, self.cp_outbox_publisher)
        self._wire_outbox_relay(cp_outbox_repo, self.cp_outbox_publisher)
        self._wire_jobs_consumers()

    def _wire_scheduled_jobs(
        self,
        cp_repo: PostgresEdiControlPlaneOutboxRepository,
        cp_pub: AwsSnsPublisher,
    ) -> None:
        cp_sweeper_use_case = OutboxSweeperUseCase(cp_repo, cp_pub)
        self.cp_sweeper_job_handler = EdiControlPlaneOutboxSweeperJobHandler(cp_sweeper_use_case)

    def _wire_outbox_relay(
        self, cp_repo: PostgresEdiControlPlaneOutboxRepository, cp_pub: AwsSnsPublisher
    ) -> None:
        outbox_processor = OutboxProcessorUseCase(
            repository=cp_repo,
            publisher=cp_pub,
        )
        self.cp_outbox_relay = PostgresOutboxRelay(
            processor=outbox_processor,
            database_url=self.settings.database.global_url,
            listen_channel=EdiConstants.OUTBOX_CHANNEL.value,
        )

    def _wire_jobs_consumers(self) -> None:
        cp_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def cp_sweeper_handler(msg: JsonDict) -> None:
            if self.cp_sweeper_job_handler:
                await self.cp_sweeper_job_handler.execute()

        cp_dispatcher.subscribe(
            EdiJobName.EDI_CONTROL_PLANE_OUTBOX_SWEEPER.value, cp_sweeper_handler
        )

        cp_sqs_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs.control_plane_jobs_queue_url,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )
        self.cp_manager = SqsConsumerManager(
            consumer=cp_sqs_consumer,
            queue_name=self.settings.sqs.control_plane_jobs_queue_url.rsplit("/", 1)[-1],
            handler=cp_dispatcher.dispatch,
        )

    async def start(self) -> None:
        if self.cp_manager:
            self.cp_manager.start()
        if self.cp_outbox_publisher and self.cp_outbox_relay:
            await self.cp_outbox_publisher.__aenter__()
            self.cp_outbox_relay.start()

    async def dispose(self) -> None:
        if self.cp_manager:
            await self.cp_manager.stop()
        if self.cp_outbox_relay and self.cp_outbox_publisher:
            await self.cp_outbox_relay.stop()
            await self.cp_outbox_publisher.__aexit__(None, None, None)
        if self.db_router:
            await self.db_router.close_all()
