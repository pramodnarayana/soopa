import asyncio

from dotenv import load_dotenv

load_dotenv()

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase
from edi.config.settings import get_settings
from worker.core.tenant_resolver import TenantResolver  # type: ignore[import-untyped]
from worker.core.tenant_uow_provider import TenantUowProvider  # type: ignore[import-untyped]

from compute_worker.worker import SQSComputeWorker

# Configure logging so it prints beautifully to the terminal
logger = structlog.get_logger("worker_runner")

async def main() -> None:
    logger.info("compute_worker_initialization_started")
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = "soopaedi-dev"

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
        uow = uow_factory()
        return ComputeTransformUseCase(uow=uow, transformer=transformer)

    queue_url = "http://localhost:4566/000000000000/TransformComputeQueue"
    worker = SQSComputeWorker(
        use_case_factory=use_case_factory,
        queue_url=queue_url,
        endpoint_url=aws_endpoint
    )

    logger.info("compute_worker_running")
    await worker.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("compute_worker_stopped_by_user")
