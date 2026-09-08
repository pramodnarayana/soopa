import structlog
from database.router import DatabaseRouter
from edi.config.settings import get_settings
from edi.domain.enums import EdiJobName
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict

from edi_dp_cleanup.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from edi_dp_cleanup.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_dp_cleanup.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
    EdiIdempotencyCleanupJobHandler,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
    SqlAlchemyEdiIdempotencyCleanupRepository,
)
from edi_dp_cleanup.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_dp_cleanup.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)

logger = structlog.get_logger(__name__)


class CleanupContainer:
    """Dependency Injection container for EDI Data Plane Cleanup jobs."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db_router = DatabaseRouter(global_db_url=self.settings.database.global_url)

        self.dp_manager: SqsConsumerManager | None = None

        self.dp_cleanup: EdiDataPlaneOutboxCleanupJobHandler | None = None
        self.idemp_cleanup: EdiIdempotencyCleanupJobHandler | None = None
        self.audit_cleanup: EdiAuditLogCleanupJobHandler | None = None

    def wire(self) -> None:
        self._wire_data_plane_jobs()

    def _wire_data_plane_jobs(self) -> None:
        dp_cleanup_repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=self.db_router)
        self.dp_cleanup = EdiDataPlaneOutboxCleanupJobHandler(OutboxCleanerUseCase(dp_cleanup_repo))

        idemp_cleanup_repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router=self.db_router)
        self.idemp_cleanup = EdiIdempotencyCleanupJobHandler(
            EdiIdempotencyCleanupUseCase(idemp_cleanup_repo)
        )

        audit_cleanup_repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=self.db_router)
        self.audit_cleanup = EdiAuditLogCleanupJobHandler(
            EdiAuditLogCleanupUseCase(audit_cleanup_repo)
        )

        dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def dp_cleanup_handler(msg: JsonDict) -> None:
            if self.dp_cleanup:
                await self.dp_cleanup.execute()

        async def idemp_cleanup_handler(msg: JsonDict) -> None:
            if self.idemp_cleanup:
                await self.idemp_cleanup.execute()

        async def audit_cleanup_handler(msg: JsonDict) -> None:
            if self.audit_cleanup:
                await self.audit_cleanup.execute()

        dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value, dp_cleanup_handler)
        dispatcher.subscribe(EdiJobName.EDI_IDEMPOTENCY_CLEANUP.value, idemp_cleanup_handler)
        dispatcher.subscribe(EdiJobName.EDI_AUDIT_LOG_CLEANUP.value, audit_cleanup_handler)

        dp_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs.data_plane_jobs_queue_url,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
        )
        self.dp_manager = SqsConsumerManager(
            consumer=dp_consumer,
            queue_name=self.settings.sqs.data_plane_jobs_queue_url.rsplit("/", 1)[-1],
            handler=dispatcher.dispatch,
        )

    async def start(self) -> None:
        if self.dp_manager:
            self.dp_manager.start()

    async def dispose(self) -> None:
        if self.dp_manager:
            await self.dp_manager.stop()
        if self.db_router:
            await self.db_router.close_all()
