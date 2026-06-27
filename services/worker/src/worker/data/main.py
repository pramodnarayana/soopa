import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Callable
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from config.settings import get_settings
from database.connection import DatabaseRouter
from pipeline.adapters.http import HttpxDeliveryAdapter
from pipeline.adapters.repository import SqlAlchemyRepositoryAdapter
from pipeline.adapters.storage import S3StorageAdapter
from pipeline.adapters.transformer import BotsTransformerAdapter
from pipeline.core.deliver import DeliveryService
from pipeline.core.translate import TranslationService
from worker.utils import TenantResolver

logger = logging.getLogger(__name__)


async def process_translation(
    trace_id: str,
    tenant_id: int,
    resolver: TenantResolver,
    db_router: DatabaseRouter,
    s3_bucket: str,
    aws_endpoint: str | None,
) -> None:
    """Sets up the Hexagonal dependencies and executes TranslationService."""
    shard_name, shard_dsn = await resolver.resolve(tenant_id)

    tenant_gen = db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
    session = await tenant_gen.__anext__()
    try:
        # Instantiate Adapters
        repo_adapter = SqlAlchemyRepositoryAdapter(session)
        storage_adapter = S3StorageAdapter(bucket_name=s3_bucket, endpoint_url=aws_endpoint)
        transformer_adapter = BotsTransformerAdapter()

        # Instantiate Domain Service
        service = TranslationService(storage_adapter, transformer_adapter, repo_adapter)

        # Execute pure domain logic
        await service.translate(trace_id)

        # Commit transaction
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await tenant_gen.__anext__()


async def process_delivery(
    trace_id: str,
    target_url: str,
    tenant_id: int,
    resolver: TenantResolver,
    db_router: DatabaseRouter,
    s3_bucket: str,
    aws_endpoint: str | None,
) -> None:
    """Sets up the Hexagonal dependencies and executes DeliveryService."""
    shard_name, shard_dsn = await resolver.resolve(tenant_id)

    tenant_gen = db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
    session = await tenant_gen.__anext__()
    try:
        # Instantiate Adapters
        repo_adapter = SqlAlchemyRepositoryAdapter(session)
        storage_adapter = S3StorageAdapter(bucket_name=s3_bucket, endpoint_url=aws_endpoint)
        http_adapter = HttpxDeliveryAdapter()

        # Instantiate Domain Service
        service = DeliveryService(storage_adapter, repo_adapter, http_adapter)

        # Execute pure domain logic
        await service.deliver(trace_id, target_url)

        # Commit transaction
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await tenant_gen.__anext__()


async def poll_sqs_queue(
    queue_name: str,
    processor_func: Callable[..., Any],
    resolver: TenantResolver,
    db_router: DatabaseRouter,
    s3_bucket: str,
    aws_endpoint: str | None,
) -> None:
    """Long-polls an SQS queue and processes messages."""
    session = aioboto3.Session()
    client_kwargs = {"region_name": "us-east-1"}
    if aws_endpoint:
        client_kwargs["endpoint_url"] = aws_endpoint

    async with session.client("sqs", **client_kwargs) as sqs:
        queue_url_resp = await sqs.get_queue_url(QueueName=queue_name)
        queue_url = queue_url_resp["QueueUrl"]

        logger.info(f"Started polling {queue_name} ({queue_url})")

        while True:
            response = await sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,
            )

            messages = response.get("Messages", [])
            for msg in messages:
                receipt_handle = msg["ReceiptHandle"]
                try:
                    body = json.loads(msg["Body"])
                    payload = body.get("payload", {})
                    trace_id = payload.get("trace_id")
                    tenant_id = body.get("tenant_id")

                    if not trace_id or not tenant_id:
                        logger.error(f"Missing trace_id or tenant_id in message: {body}")
                        continue

                    logger.info(f"[{queue_name}] Processing trace_id={trace_id}")

                    # Determine target_url if DELIVER
                    kwargs = {
                        "trace_id": trace_id,
                        "tenant_id": tenant_id,
                        "resolver": resolver,
                        "db_router": db_router,
                        "s3_bucket": s3_bucket,
                        "aws_endpoint": aws_endpoint,
                    }
                    if queue_name == "DeliverQueue":
                        kwargs["target_url"] = payload.get("target", "https://example.com/webhook")

                    await processor_func(**kwargs)

                    # Delete message on success
                    await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                    logger.info(
                        f"[{queue_name}] Successfully processed and deleted trace_id={trace_id}"
                    )

                except Exception as e:
                    logger.exception(f"[{queue_name}] Error processing message: {e}")


async def main() -> None:
    settings = get_settings()
    aws_endpoint = os.getenv("AWS_ENDPOINT_URL")
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    translate_task = asyncio.create_task(
        poll_sqs_queue(
            "TranslateQueue", process_translation, resolver, db_router, s3_bucket, aws_endpoint
        )
    )
    deliver_task = asyncio.create_task(
        poll_sqs_queue(
            "DeliverQueue", process_delivery, resolver, db_router, s3_bucket, aws_endpoint
        )
    )

    await asyncio.gather(translate_task, deliver_task)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
