import asyncio
import os
from typing import Any

import structlog
from config.settings import get_settings
from database.connection import DatabaseRouter
from domain.events import MessageQueueName
from dotenv import load_dotenv

from worker.adapters.sqs_poller import poll_sqs_queue
from worker.adapters.sqs_publisher import SqsPublisherAdapter
from worker.core.scheduler.models import JobName
from worker.core.tenant_resolver import TenantResolver
from worker.data.handlers import process_delivery, process_pipeline_event

load_dotenv()
logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    async def pipeline_processor(body: dict[str, Any]) -> None:
        payload = body.get("payload", {})
        trace_id = payload.get("trace_id")
        tenant_id = body.get("tenant_id")
        if not trace_id or not tenant_id:
            logger.error("missing_trace_id_or_tenant_id", trace_id=trace_id, tenant_id=tenant_id)
            return
        await process_pipeline_event(
            trace_id=trace_id,
            event_type=body.get("event_type", "UNKNOWN"),
            payload=payload,
            tenant_id=tenant_id,
            resolver=resolver,
            db_router=db_router,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
            idempotency_key=body.get("idempotency_key"),
        )

    transform_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
            pipeline_processor,
            aws_endpoint,
        )
    )

    async def delivery_processor(body: dict[str, Any]) -> None:
        payload = body.get("payload", {})
        trace_id = payload.get("trace_id")
        tenant_id = body.get("tenant_id")
        if not trace_id or not tenant_id:
            logger.error("missing_trace_id_or_tenant_id", trace_id=trace_id, tenant_id=tenant_id)
            return
        await process_delivery(
            trace_id=trace_id,
            event_type=body.get("event_type", "UNKNOWN"),
            payload=payload,
            tenant_id=tenant_id,
            resolver=resolver,
            db_router=db_router,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
            idempotency_key=body.get("idempotency_key"),
        )

    deliver_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.DELIVER_QUEUE,
            delivery_processor,
            aws_endpoint,
        )
    )

    # Register Job Handlers
    from worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import EdiAuditLogCleanupJobHandler
    from worker.adapters.inbound.jobs.edi_control_plane_outbox_cleanup_job import (
        EdiControlPlaneOutboxCleanupJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_control_plane_outbox_sweeper_job import (
        EdiControlPlaneOutboxSweeperJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
        EdiDataPlaneOutboxCleanupJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_data_plane_outbox_sweeper_job import (
        EdiDataPlaneOutboxSweeperJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
        EdiIdempotencyCleanupJobHandler,
    )
    from worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
        SqlAlchemyEdiAuditLogCleanupRepository,
    )
    from worker.adapters.outbound.database.postgres_edi_control_plane_outbox_cleanup_repository import (
        SqlAlchemyEdiControlPlaneOutboxCleanupRepository,
    )
    from worker.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
        SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
    )
    from worker.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
        SqlAlchemyEdiIdempotencyCleanupRepository,
    )
    from worker.adapters.postgres_outbox_relay_repository import PostgresOutboxRelayRepository
    from worker.application.edi_audit_log_cleanup_use_case import EdiAuditLogCleanupUseCase
    from worker.application.edi_control_plane_outbox_cleanup_use_case import (
        EdiControlPlaneOutboxCleanupUseCase,
    )
    from worker.application.edi_control_plane_outbox_sweeper_use_case import (
        EdiControlPlaneOutboxSweeperUseCase,
    )
    from worker.application.edi_data_plane_outbox_cleanup_use_case import (
        EdiDataPlaneOutboxCleanupUseCase,
    )
    from worker.application.edi_data_plane_outbox_sweeper_use_case import (
        EdiDataPlaneOutboxSweeperUseCase,
    )
    from worker.application.edi_idempotency_cleanup_use_case import EdiIdempotencyCleanupUseCase
    from worker.core.job_registry import JobHandlerRegistry

    message_publisher = SqsPublisherAdapter(
        endpoint_url=settings.aws.endpoint_url,
        region=settings.aws.resolved_region,
    )

    outbox_relay_repository = PostgresOutboxRelayRepository(db_router=db_router)

    edi_cp_outbox_cleanup_repo = SqlAlchemyEdiControlPlaneOutboxCleanupRepository(
        db_router=db_router
    )
    edi_dp_outbox_cleanup_repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=db_router)
    edi_idemp_cleanup_repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router=db_router)
    edi_audit_cleanup_repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    orchestrator_sweeper_use_case = EdiDataPlaneOutboxSweeperUseCase(db_router, message_publisher)
    provisioning_sweeper_use_case = EdiControlPlaneOutboxSweeperUseCase(outbox_relay_repository)

    edi_cp_outbox_cleanup_uc = EdiControlPlaneOutboxCleanupUseCase(edi_cp_outbox_cleanup_repo)
    edi_dp_outbox_cleanup_uc = EdiDataPlaneOutboxCleanupUseCase(edi_dp_outbox_cleanup_repo)
    edi_idemp_cleanup_uc = EdiIdempotencyCleanupUseCase(edi_idemp_cleanup_repo)
    edi_audit_cleanup_uc = EdiAuditLogCleanupUseCase(edi_audit_cleanup_repo)

    registry = JobHandlerRegistry()
    registry.register(
        JobName.EDI_ORCHESTRATOR_OUTBOX_SWEEPER.value,
        EdiDataPlaneOutboxSweeperJobHandler(orchestrator_sweeper_use_case),
    )
    registry.register(
        JobName.EDI_PROVISIONING_OUTBOX_SWEEPER.value,
        EdiControlPlaneOutboxSweeperJobHandler(provisioning_sweeper_use_case),
    )
    registry.register(
        JobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value,
        EdiControlPlaneOutboxCleanupJobHandler(edi_cp_outbox_cleanup_uc),
    )
    registry.register(
        JobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value,
        EdiDataPlaneOutboxCleanupJobHandler(edi_dp_outbox_cleanup_uc),
    )
    registry.register(
        JobName.EDI_IDEMPOTENCY_CLEANUP.value, EdiIdempotencyCleanupJobHandler(edi_idemp_cleanup_uc)
    )
    registry.register(
        JobName.EDI_AUDIT_LOG_CLEANUP.value, EdiAuditLogCleanupJobHandler(edi_audit_cleanup_uc)
    )

    import functools

    from worker.data.scheduled_jobs_handler import process_scheduled_job

    scheduled_jobs_processor = functools.partial(process_scheduled_job, registry=registry)

    scheduled_jobs_task = asyncio.create_task(
        poll_sqs_queue(
            "edi-orchestrator-jobs",
            scheduled_jobs_processor,
            aws_endpoint,
        )
    )

    try:
        # We only need to gather the SQS listeners!
        # UCP's scheduler engine will push scheduled jobs to the edi-orchestrator-jobs queue automatically.
        await asyncio.gather(transform_task, deliver_task, scheduled_jobs_task)
    finally:
        logger.info("Shutting down data worker tasks gracefully...")
        transform_task.cancel()
        deliver_task.cancel()
        scheduled_jobs_task.cancel()

        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(
                transform_task, deliver_task, scheduled_jobs_task, return_exceptions=True
            )

        if db_router:
            await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
