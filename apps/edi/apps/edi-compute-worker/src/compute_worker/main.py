import asyncio
import signal

from dotenv import load_dotenv

load_dotenv()

import aioboto3
import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.adapters.outbound.database.tenant_uow_provider import TenantUowProvider
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase
from edi.config.settings import get_settings

from compute_worker.worker import SQSComputeWorker

# Configure logging so it prints beautifully to the terminal
logger = structlog.get_logger("worker_runner")


async def main() -> None:
    logger.info("compute_worker_initialization_started")
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = settings.s3.bucket

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    transformer = BotsTransformerAdapter()

    uow_provider = TenantUowProvider(
        resolver=resolver,
        db_router=db_router,
        settings=settings,
        s3_bucket=s3_bucket,
        aws_endpoint=aws_endpoint,
    )

    async def use_case_factory(tenant_id: str) -> ComputeTransformUseCase:
        uow_factory = await uow_provider.get_uow_factory(tenant_id)
        from typing import cast

        from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

        uow = cast(DataPlaneUnitOfWorkPort, uow_factory())
        return ComputeTransformUseCase(uow=uow, transformer=transformer)

    # Resolve SQS Queue URL dynamically
    session = aioboto3.Session()
    client_kwargs = {"region_name": "us-east-1"}
    if aws_endpoint:
        client_kwargs["endpoint_url"] = aws_endpoint

    async with session.client("sqs", **client_kwargs) as sqs:
        queue_name = (
            settings.aws.sqs_transform_queue_name
            if hasattr(settings.aws, "sqs_transform_queue_name")
            else "TransformComputeQueue"
        )
        response = await sqs.get_queue_url(QueueName=queue_name)
        queue_url = response["QueueUrl"]

    worker = SQSComputeWorker(
        use_case_factory=use_case_factory, queue_url=queue_url, endpoint_url=aws_endpoint
    )

    # Handle shutdown signals
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def shutdown_handler(*args: object) -> None:
        logger.info("compute_worker_shutdown_signal_received")
        stop_event.set()

    loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    logger.info("compute_worker_running")
    worker_task = asyncio.create_task(worker.start())

    await stop_event.wait()
    logger.info("compute_worker_stopping")
    await worker.stop()
    await worker_task
    logger.info("compute_worker_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("compute_worker_stopped_by_user")
