import asyncio
import functools
import signal

import structlog
from dotenv import load_dotenv
from edi.adapters.inbound.messaging.sqs_poller import poll_sqs_queue
from edi.adapters.outbound.database.connection import DatabaseRouter

# We need the outbox publisher and sqs poller
# They were in orchestrator-worker, but let's copy them or import them if they are still there
from edi.adapters.outbound.messaging.edi_data_plane_sqs_outbox_publisher import (
    EdiDataPlaneSqsOutboxPublisherAdapter,
)
from edi.config.settings import get_settings
from outbox.application.outbox_cleanup_use_case import OutboxCleanupUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase

from edi_background_worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_data_plane_outbox_sweeper_job import (
    EdiDataPlaneOutboxSweeperJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
    EdiIdempotencyCleanupJobHandler,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
    SqlAlchemyEdiIdempotencyCleanupRepository,
)
from edi_background_worker.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_background_worker.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)
from edi_background_worker.constants import EdiJobName
from edi_background_worker.domain.job_registry import JobHandlerRegistry
from edi_background_worker.scheduled_jobs_handler import process_scheduled_job

load_dotenv()
logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("edi_background_worker.starting")
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    message_publisher = EdiDataPlaneSqsOutboxPublisherAdapter(
        endpoint_url=settings.aws.endpoint_url,
        region=settings.aws.resolved_region,
    )

    edi_dp_outbox_cleanup_repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=db_router)
    edi_idemp_cleanup_repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router=db_router)
    edi_audit_cleanup_repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    data_plane_repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)
    data_plane_sweeper_use_case = OutboxSweeperUseCase(
        repository=data_plane_repo,
        publisher=message_publisher,
    )

    job_registry = JobHandlerRegistry()
    job_registry.register(
        EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value,
        EdiDataPlaneOutboxSweeperJobHandler(data_plane_sweeper_use_case),
    )
    job_registry.register(
        EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value,
        EdiDataPlaneOutboxCleanupJobHandler(OutboxCleanupUseCase(edi_dp_outbox_cleanup_repo)),
    )
    job_registry.register(
        EdiJobName.EDI_IDEMPOTENCY_CLEANUP.value,
        EdiIdempotencyCleanupJobHandler(EdiIdempotencyCleanupUseCase(edi_idemp_cleanup_repo)),
    )
    job_registry.register(
        EdiJobName.EDI_AUDIT_LOG_CLEANUP.value,
        EdiAuditLogCleanupJobHandler(EdiAuditLogCleanupUseCase(edi_audit_cleanup_repo)),
    )

    from config_sync_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_repository import (
        PostgresEdiControlPlaneOutboxRepository,
    )
    from pubsub.aws.aws_sns_publisher import AwsSnsPublisher

    from edi_background_worker.adapters.inbound.jobs.edi_control_plane_outbox_cleanup_job import (
        EdiControlPlaneOutboxCleanupJobHandler,
    )
    from edi_background_worker.adapters.inbound.jobs.edi_control_plane_outbox_sweeper_job import (
        EdiControlPlaneOutboxSweeperJobHandler,
    )
    from edi_background_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_cleanup_repository import (
        SqlAlchemyEdiControlPlaneOutboxCleanupRepository,
    )

    control_plane_outbox_repo = PostgresEdiControlPlaneOutboxRepository(db_router=db_router)
    control_plane_publisher = AwsSnsPublisher(
        topic_arn=settings.aws.sns_topic_arn,
        endpoint_url=settings.aws.endpoint_url,
        region_name=settings.aws.default_region,
    )
    control_plane_sweeper_use_case = OutboxSweeperUseCase(
        repository=control_plane_outbox_repo,
        publisher=control_plane_publisher,
    )
    edi_cp_outbox_cleanup_repo = SqlAlchemyEdiControlPlaneOutboxCleanupRepository(
        db_router=db_router
    )

    job_registry.register(
        EdiJobName.EDI_CONTROL_PLANE_OUTBOX_SWEEPER.value,
        EdiControlPlaneOutboxSweeperJobHandler(control_plane_sweeper_use_case),
    )
    job_registry.register(
        EdiJobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value,
        EdiControlPlaneOutboxCleanupJobHandler(OutboxCleanupUseCase(edi_cp_outbox_cleanup_repo)),
    )

    data_plane_jobs_task = asyncio.create_task(
        poll_sqs_queue(
            "edi-data-plane-jobs.fifo",
            functools.partial(process_scheduled_job, registry=job_registry),
            aws_endpoint,
        )
    )
    control_plane_jobs_task = asyncio.create_task(
        poll_sqs_queue(
            "edi-control-plane-jobs.fifo",
            functools.partial(process_scheduled_job, registry=job_registry),
            aws_endpoint,
        )
    )

    def shutdown_handler(*args: object) -> None:
        logger.info("edi_background_worker_shutdown_signal_received")
        data_plane_jobs_task.cancel()
        control_plane_jobs_task.cancel()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    try:
        await asyncio.gather(data_plane_jobs_task, control_plane_jobs_task)
    except asyncio.CancelledError:
        logger.info("edi_background_worker_cancelled")
    finally:
        logger.info("edi_background_worker_stopped")
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
