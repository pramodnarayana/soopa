import os

import structlog
from database.provider import DatabaseProvider
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict
from ucp.adapters.outbound.database.postgres_ucp_audit_log_cleanup_repository import (
    SqlAlchemyUcpAuditLogCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_idempotency_cleanup_repository import (
    SqlAlchemyUcpIdempotencyCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_outbox_cleanup_repository import (
    SqlAlchemyUcpOutboxCleanupRepository,
)
from ucp.application.use_cases.ucp_audit_log_cleanup_use_case import UcpAuditLogCleanupUseCase
from ucp.application.use_cases.ucp_idempotency_cleanup_use_case import UcpIdempotencyCleanupUseCase
from ucp.config.settings import get_settings

from ucp_cleanup.adapters.inbound.jobs.ucp_audit_log_cleanup_job import UcpAuditLogCleanupJobHandler
from ucp_cleanup.adapters.inbound.jobs.ucp_idempotency_cleanup_job import (
    UcpIdempotencyCleanupJobHandler,
)
from ucp_cleanup.adapters.inbound.jobs.ucp_outbox_cleanup_job import UcpOutboxCleanupJobHandler
from ucp_cleanup.constants import UcpCleanupJobName

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the UCP Cleanup Worker."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.database_url = os.environ.get("DATABASE_URL", "")
        self.db_provider = DatabaseProvider.from_url(self.database_url)
        self.session_factory = self.db_provider.session_factory

        self.jobs_consumer: SqsConsumerManager | None = None

        self.outbox_cleanup_job_handler: UcpOutboxCleanupJobHandler | None = None
        self.idemp_cleanup_job_handler: UcpIdempotencyCleanupJobHandler | None = None
        self.audit_cleanup_job_handler: UcpAuditLogCleanupJobHandler | None = None

    def wire(self) -> None:
        self._wire_scheduled_jobs()
        self._wire_jobs_consumer()

    def _wire_scheduled_jobs(self) -> None:
        outbox_cleanup_repo = SqlAlchemyUcpOutboxCleanupRepository(self.session_factory)
        idemp_cleanup_repo = SqlAlchemyUcpIdempotencyCleanupRepository(self.session_factory)
        audit_cleanup_repo = SqlAlchemyUcpAuditLogCleanupRepository(self.session_factory)

        outbox_cleaner_use_case = OutboxCleanerUseCase(outbox_cleanup_repo)
        idemp_cleanup_use_case = UcpIdempotencyCleanupUseCase(idemp_cleanup_repo)
        audit_cleanup_use_case = UcpAuditLogCleanupUseCase(audit_cleanup_repo)

        self.outbox_cleanup_job_handler = UcpOutboxCleanupJobHandler(outbox_cleaner_use_case)
        self.idemp_cleanup_job_handler = UcpIdempotencyCleanupJobHandler(idemp_cleanup_use_case)
        self.audit_cleanup_job_handler = UcpAuditLogCleanupJobHandler(audit_cleanup_use_case)

    def _wire_jobs_consumer(self) -> None:
        job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def outbox_cleanup_handler(message: JsonDict) -> None:
            if self.outbox_cleanup_job_handler:
                await self.outbox_cleanup_job_handler.execute()

        async def idemp_cleanup_handler(message: JsonDict) -> None:
            if self.idemp_cleanup_job_handler:
                await self.idemp_cleanup_job_handler.execute()

        async def audit_cleanup_handler(message: JsonDict) -> None:
            if self.audit_cleanup_job_handler:
                await self.audit_cleanup_job_handler.execute()

        job_dispatcher.subscribe(UcpCleanupJobName.UCP_OUTBOX_CLEANUP.value, outbox_cleanup_handler)
        job_dispatcher.subscribe(
            UcpCleanupJobName.UCP_IDEMPOTENCY_CLEANUP.value, idemp_cleanup_handler
        )
        job_dispatcher.subscribe(
            UcpCleanupJobName.UCP_AUDIT_LOG_CLEANUP.value, audit_cleanup_handler
        )

        jobs_sqs_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs_ucp_jobs_queue_url,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self.jobs_consumer = SqsConsumerManager(
            consumer=jobs_sqs_consumer,
            queue_name="ucp-jobs.fifo",
            handler=job_dispatcher.dispatch,
        )

    async def dispose(self) -> None:
        if self.db_provider:
            await self.db_provider.close()
