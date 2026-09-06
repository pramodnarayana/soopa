import asyncio
import signal
from typing import Any

import structlog
from config_sync_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_repository import (
    PostgresEdiControlPlaneOutboxRepository,
)
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.config.settings import AppSettings, get_settings
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from edi_background_worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_control_plane_outbox_cleanup_job import (
    EdiControlPlaneOutboxCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_control_plane_outbox_sweeper_job import (
    EdiControlPlaneOutboxSweeperJobHandler,
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
from edi_background_worker.adapters.inbound.workers.edi_job_dispatcher import EdiJobDispatcher
from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiControlPlaneOutboxCleanupRepository,
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

load_dotenv()
logger = structlog.get_logger(__name__)


def _build_dp_dispatcher(db_router: DatabaseRouter, settings: AppSettings) -> EdiJobDispatcher:
    """Builds and wires the data-plane job dispatcher."""
    message_publisher = AwsSqsPublisher(
        queue_url=settings.sqs.data_plane_jobs_queue_url,
        endpoint_url=settings.aws.endpoint_url,
        region_name=settings.aws.resolved_region,
    )

    dp_outbox_repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)
    dp_sweeper = EdiDataPlaneOutboxSweeperJobHandler(
        OutboxSweeperUseCase(repository=dp_outbox_repo, publisher=message_publisher)
    )

    dp_cleanup_repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=db_router)
    dp_cleanup = EdiDataPlaneOutboxCleanupJobHandler(OutboxCleanerUseCase(dp_cleanup_repo))

    idemp_cleanup_repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router=db_router)
    idemp_cleanup = EdiIdempotencyCleanupJobHandler(
        EdiIdempotencyCleanupUseCase(idemp_cleanup_repo)
    )

    audit_cleanup_repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)
    audit_cleanup = EdiAuditLogCleanupJobHandler(EdiAuditLogCleanupUseCase(audit_cleanup_repo))

    dispatcher = EdiJobDispatcher()

    async def dp_sweeper_handler(msg: dict[str, Any]) -> None:
        await dp_sweeper.execute()

    async def dp_cleanup_handler(msg: dict[str, Any]) -> None:
        await dp_cleanup.execute()

    async def idemp_cleanup_handler(msg: dict[str, Any]) -> None:
        await idemp_cleanup.execute()

    async def audit_cleanup_handler(msg: dict[str, Any]) -> None:
        await audit_cleanup.execute()

    dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value, dp_sweeper_handler)
    dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value, dp_cleanup_handler)
    dispatcher.subscribe(EdiJobName.EDI_IDEMPOTENCY_CLEANUP.value, idemp_cleanup_handler)
    dispatcher.subscribe(EdiJobName.EDI_AUDIT_LOG_CLEANUP.value, audit_cleanup_handler)

    return dispatcher


def _build_cp_dispatcher(db_router: DatabaseRouter, settings: AppSettings) -> EdiJobDispatcher:
    """Builds and wires the control-plane job dispatcher."""
    cp_publisher = AwsSnsPublisher(
        topic_arn=settings.aws.sns_topic_arn,
        endpoint_url=settings.aws.endpoint_url,
        region_name=settings.aws.default_region,
    )

    cp_outbox_repo = PostgresEdiControlPlaneOutboxRepository(db_router=db_router)
    cp_sweeper = EdiControlPlaneOutboxSweeperJobHandler(
        OutboxSweeperUseCase(repository=cp_outbox_repo, publisher=cp_publisher)
    )

    cp_cleanup_repo = SqlAlchemyEdiControlPlaneOutboxCleanupRepository(db_router=db_router)
    cp_cleanup = EdiControlPlaneOutboxCleanupJobHandler(OutboxCleanerUseCase(cp_cleanup_repo))

    dispatcher = EdiJobDispatcher()

    async def cp_sweeper_handler(msg: dict[str, Any]) -> None:
        await cp_sweeper.execute()

    async def cp_cleanup_handler(msg: dict[str, Any]) -> None:
        await cp_cleanup.execute()

    dispatcher.subscribe(EdiJobName.EDI_CONTROL_PLANE_OUTBOX_SWEEPER.value, cp_sweeper_handler)
    dispatcher.subscribe(EdiJobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value, cp_cleanup_handler)

    return dispatcher


async def _run_until_shutdown(
    dp_manager: SqsConsumerManager,
    cp_manager: SqsConsumerManager,
) -> None:
    """Blocks until a stop signal is received or a consumer task fails."""
    stop_event = asyncio.Event()

    def shutdown_handler(*args: object) -> None:
        logger.info("edi_background_worker_shutdown_signal_received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    stop_task = asyncio.create_task(stop_event.wait())
    tasks: list[asyncio.Task[Any]] = [stop_task]
    if dp_manager._task:
        tasks.append(dp_manager._task)
    if cp_manager._task:
        tasks.append(cp_manager._task)

    done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in done:
        if task is not stop_task and task.exception():
            exc = task.exception()
            logger.error("sqs_consumer_manager_failed", exc_info=exc)
            if exc:
                raise exc


async def main() -> None:
    logger.info("edi_background_worker.starting")
    settings = get_settings()

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    dp_dispatcher = _build_dp_dispatcher(db_router, settings)
    cp_dispatcher = _build_cp_dispatcher(db_router, settings)

    dp_consumer = AwsSqsConsumer(
        queue_url=settings.sqs.data_plane_jobs_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )
    cp_consumer = AwsSqsConsumer(
        queue_url=settings.sqs.control_plane_jobs_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )

    dp_manager = SqsConsumerManager(
        consumer=dp_consumer,
        queue_name=settings.sqs.data_plane_jobs_queue_url.rsplit("/", 1)[-1],
        handler=dp_dispatcher.dispatch,
    )
    dp_manager.start()

    cp_manager = SqsConsumerManager(
        consumer=cp_consumer,
        queue_name=settings.sqs.control_plane_jobs_queue_url.rsplit("/", 1)[-1],
        handler=cp_dispatcher.dispatch,
    )
    cp_manager.start()

    try:
        await _run_until_shutdown(dp_manager, cp_manager)
    except asyncio.CancelledError:
        logger.info("edi_background_worker_cancelled")
    except Exception:
        logger.exception("edi_background_worker_failed")
        raise
    finally:
        results = await asyncio.gather(
            dp_manager.stop(),
            cp_manager.stop(),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                logger.error("manager_stop_failed", exc_info=res)
        logger.info("edi_background_worker_stopped")
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
