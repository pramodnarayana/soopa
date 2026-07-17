import asyncio
import logging
import os
from typing import Any

from config.settings import get_settings
from database.connection import DatabaseRouter
from domain.events import MessageQueueName
from dotenv import load_dotenv
from scheduler.adapters.repository import SqlAlchemyJobRepository
from scheduler.core.service import SchedulerWorkerService
from worker.adapters.sqs_poller import poll_sqs_queue
from worker.adapters.sqs_publisher import SqsPublisherAdapter
from worker.core.tenant_resolver import TenantResolver
from worker.data.handlers import process_delivery, process_pipeline_event

load_dotenv()
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = os.getenv("AWS_ENDPOINT_URL")
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    async def pipeline_processor(body: dict[str, Any]) -> None:
        payload = body.get("payload", {})
        trace_id = payload.get("trace_id")
        tenant_id = body.get("tenant_id")
        if not trace_id or not tenant_id:
            logger.error(f"Missing trace_id or tenant_id in message: {body}")
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
            logger.error(f"Missing trace_id or tenant_id in message: {body}")
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

    # Start Scheduler worker
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database.global_url)
    scheduler_repo = SqlAlchemyJobRepository(engine)
    message_publisher = SqsPublisherAdapter(
        endpoint_url=settings.aws.endpoint_url,
        region=settings.aws.resolved_region,
    )

    scheduler_service = SchedulerWorkerService(
        scheduler_repo, publisher=message_publisher, worker_id=f"orchestrator-{os.getpid()}"
    )

    from scheduler.domain.models import JobName
    from worker.core.job_registry import JobHandlerRegistry
    from worker.jobs.data_retention import DataRetentionCleanupJobHandler
    from worker.jobs.outbox_sweeper import DataPlaneOutboxSweeperJobHandler

    registry = JobHandlerRegistry()
    registry.register(
        JobName.OUTBOX_SWEEPER.value, DataPlaneOutboxSweeperJobHandler(db_router, message_publisher)
    )
    registry.register(
        JobName.DATA_RETENTION_CLEANUP.value, DataRetentionCleanupJobHandler(db_router)
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

    # Run the scheduler loop in the background
    await scheduler_service.start(poll_interval_seconds=10.0)

    await asyncio.gather(transform_task, deliver_task, scheduled_jobs_task)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
