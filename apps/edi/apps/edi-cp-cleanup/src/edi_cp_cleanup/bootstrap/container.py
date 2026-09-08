import structlog
from database.router import DatabaseRouter
from edi.config.settings import get_settings
from edi.domain.enums import EdiJobName
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from edi_cp_cleanup.adapters.inbound.jobs.edi_control_plane_outbox_cleanup_job import (
    EdiControlPlaneOutboxCleanupJobHandler,
)
from edi_cp_cleanup.adapters.outbound.database.postgres_edi_control_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiControlPlaneOutboxCleanupRepository,
)

logger = structlog.get_logger(__name__)


class CleanupContainer:
    """Dependency Injection container for EDI Control Plane Cleanup jobs."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db_router = DatabaseRouter(global_db_url=self.settings.database.global_url)

        self.cp_manager: SqsConsumerManager | None = None
        self.cp_cleanup: EdiControlPlaneOutboxCleanupJobHandler | None = None

    def wire(self) -> None:
        self._wire_control_plane_jobs()

    def _wire_control_plane_jobs(self) -> None:
        cp_cleanup_repo = SqlAlchemyEdiControlPlaneOutboxCleanupRepository(db_router=self.db_router)
        self.cp_cleanup = EdiControlPlaneOutboxCleanupJobHandler(
            OutboxCleanerUseCase(cp_cleanup_repo)
        )

        dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def cp_cleanup_handler(msg: JsonDict) -> None:
            if self.cp_cleanup:
                await self.cp_cleanup.execute()

        dispatcher.subscribe(EdiJobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value, cp_cleanup_handler)

        cp_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs.control_plane_jobs_queue_url,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )
        self.cp_manager = SqsConsumerManager(
            consumer=cp_consumer,
            queue_name=self.settings.sqs.control_plane_jobs_queue_url.rsplit("/", 1)[-1],
            handler=dispatcher.dispatch,
        )

    async def start(self) -> None:
        if self.cp_manager:
            self.cp_manager.start()

    async def dispose(self) -> None:
        if self.cp_manager:
            await self.cp_manager.stop()
        if self.db_router:
            await self.db_router.close_all()
