import asyncio
import contextlib
import ipaddress
import json
import logging
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import aioboto3  # type: ignore[import-untyped]
from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models import DatabaseShard, Tenant
from domain.events import MessageQueueName
from dotenv import load_dotenv
from pipeline.adapters.as2 import HttpxAS2DeliveryAdapter
from pipeline.adapters.http import HttpxDeliveryAdapter
from pipeline.adapters.repository import SqlAlchemyRepositoryAdapter
from pipeline.adapters.sftp import ParamikoSftpDeliveryAdapter
from pipeline.adapters.storage import S3StorageAdapter
from pipeline.adapters.transformer import BotsTransformerAdapter
from pipeline.core.delivery import (
    As2DeliveryStrategy,
    DeliveryRouter,
    SftpDeliveryStrategy,
    WebhookDeliveryStrategy,
)
from pipeline.core.transformation import InboundTransformService, OutboundTransformService
from sqlalchemy import select
from worker.adapters.vault import WorkerVaultAdapter

load_dotenv()


class TenantResolver:
    """
    Caches tenant-to-shard mapping to avoid querying the Global DB on every SQS message.
    """

    def __init__(self, db_router: DatabaseRouter, ttl_secs: int = 300):
        self.db_router = db_router
        self._cache: dict[int, tuple[str, str, float]] = {}
        self._ttl = ttl_secs

    async def resolve(self, tenant_id: int) -> tuple[str, str]:
        import time

        now = time.time()
        if tenant_id in self._cache:
            shard_name, shard_dsn, expiry = self._cache[tenant_id]
            if now < expiry:
                return shard_name, shard_dsn

        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = select(Tenant, DatabaseShard).join(DatabaseShard).where(Tenant.id == tenant_id)
            result = await global_session.execute(stmt)
            row = result.first()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found in Global DB")
            _, shard_obj = row
            self._cache[tenant_id] = (str(shard_obj.name), str(shard_obj.dsn), now + self._ttl)
            return str(shard_obj.name), str(shard_obj.dsn)
        finally:
            await global_gen.aclose()


logger = logging.getLogger(__name__)


def validate_target_url(url: str) -> bool:
    """
    Validate target URL to prevent SSRF attacks.
    Returns True if URL is safe, False otherwise.
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https schemes
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"SSRF check failed: invalid scheme {parsed.scheme}")
            return False

        # Reject URLs without a hostname
        if not parsed.hostname:
            logger.warning("SSRF check failed: missing hostname")
            return False

        # Resolve all A/AAAA records for the hostname
        import socket

        try:
            # getaddrinfo returns a list of 5-tuples: (family, type, proto, canonname, sockaddr)
            addr_info = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror:
            logger.warning(f"SSRF check failed: could not resolve hostname {parsed.hostname}")
            return False

        for addr in addr_info:
            ip_str = addr[4][0]
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                logger.warning(f"SSRF check failed: resolved to private/internal IP {ip}")
                return False

        return True
    except Exception as e:
        logger.error(f"SSRF validation error: {e}")
        return False


async def process_pipeline_event(
    trace_id: str,
    event_type: str,
    payload: dict[str, Any],
    tenant_id: int,
    resolver: TenantResolver,
    db_router: DatabaseRouter,
    s3_bucket: str,
    aws_endpoint: str | None,
) -> None:
    """Sets up the Hexagonal dependencies and executes TransformService or Saga Coordinator."""
    shard_name, shard_dsn = await resolver.resolve(tenant_id)

    tenant_gen = db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
    session = await tenant_gen.__anext__()
    try:
        storage_adapter = S3StorageAdapter(bucket_name=s3_bucket, endpoint_url=aws_endpoint)
        repo_adapter = SqlAlchemyRepositoryAdapter(
            session=session,
            settings=get_settings(),
            storage=storage_adapter,
        )
        transformer_adapter = BotsTransformerAdapter()

        from domain.events import PipelineEventType

        if event_type in (
            PipelineEventType.TRANSFORM_COMPLETED,
            PipelineEventType.DELIVERY_COMPLETED,
        ):
            from pipeline.core.saga import TraceLifecycleService

            saga_service = TraceLifecycleService(repo_adapter)
            if event_type == PipelineEventType.TRANSFORM_COMPLETED:
                await saga_service.handle_transform_completed(payload)
            else:
                await saga_service.handle_delivery_completed(payload)
        else:
            # Resolve direction first
            from domain.direction import MessageDirection

            direction_str = payload.get("direction", MessageDirection.INBOUND.value)
            direction = (
                MessageDirection.OUTBOUND
                if direction_str.upper() == MessageDirection.OUTBOUND.value
                else MessageDirection.INBOUND
            )

            # Execute pure domain logic
            service = (
                InboundTransformService(transformer_adapter, repo_adapter)
                if direction == MessageDirection.INBOUND
                else OutboundTransformService(transformer_adapter, repo_adapter)
            )
            print(f"[WORKER] Transforming trace_id={trace_id}")

            await service.transform(trace_id)
            print(f"[WORKER] SUCCESS transforming trace_id={trace_id}")

        # Commit transaction
        await session.commit()
    except Exception as e:
        print(f"[WORKER] FAILURE in process_transformation for trace_id={trace_id}: {e}")
        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await tenant_gen.__anext__()


async def process_delivery(
    trace_id: str,
    event_type: str,
    payload: dict[str, Any],
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
        storage_adapter = S3StorageAdapter(bucket_name=s3_bucket, endpoint_url=aws_endpoint)
        repo_adapter = SqlAlchemyRepositoryAdapter(
            session=session,
            settings=get_settings(),
            storage=storage_adapter,
        )
        http_adapter = HttpxDeliveryAdapter(validator=validate_target_url)
        sftp_adapter = ParamikoSftpDeliveryAdapter()
        vault_adapter = WorkerVaultAdapter()
        as2_adapter = HttpxAS2DeliveryAdapter()

        # Instantiate Domain Service
        strategies = {
            "webhook_id": WebhookDeliveryStrategy(repo_adapter, http_adapter, vault_adapter),
            "sftp_partner_id": SftpDeliveryStrategy(repo_adapter, sftp_adapter, vault_adapter),
            "as2_partner_id": As2DeliveryStrategy(repo_adapter, as2_adapter, vault_adapter),
        }
        service = DeliveryRouter(
            repository=repo_adapter,
            strategies=strategies,
        )

        # Execute pure domain logic
        await service.deliver(trace_id)

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

    while True:
        try:
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
                                # Permanently delete unrecoverable messages to prevent re-drive loops
                                await sqs.delete_message(
                                    QueueUrl=queue_url, ReceiptHandle=receipt_handle
                                )
                                logger.warning(
                                    f"[{queue_name}] Deleted poison message with missing ids"
                                )
                                continue

                            logger.info(f"[{queue_name}] Processing trace_id={trace_id}")
                            kwargs: dict[str, Any] = {
                                "trace_id": trace_id,
                                "event_type": body.get("event_type", "UNKNOWN"),
                                "payload": payload,
                                "tenant_id": tenant_id,
                                "resolver": resolver,
                                "db_router": db_router,
                                "s3_bucket": s3_bucket,
                                "aws_endpoint": aws_endpoint,
                            }
                            await processor_func(**kwargs)

                            # Delete message on success
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )
                            logger.info(
                                f"[{queue_name}] Successfully processed trace_id={trace_id}"
                            )

                        except json.JSONDecodeError:
                            # Permanently delete malformed (non-JSON) messages
                            logger.error(
                                f"[{queue_name}] Non-JSON message body, deleting permanently"
                            )
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )
                        except (KeyError, NotImplementedError) as e:
                            # Permanently delete messages with unrecoverable configuration errors
                            logger.error(
                                f"[{queue_name}] Permanent validation error, deleting permanently: {e}"
                            )
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )
                        except Exception as e:
                            logger.exception(
                                f"[{queue_name}] Transient error processing message: {e}"
                            )
        except Exception as e:
            logger.exception(f"[{queue_name}] SQS client error, retrying in 2s: {e}")
            await asyncio.sleep(2)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = os.getenv("AWS_ENDPOINT_URL")
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    transform_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
            process_pipeline_event,
            resolver,
            db_router,
            s3_bucket,
            aws_endpoint,
        )
    )
    deliver_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.DELIVER_QUEUE,
            process_delivery,
            resolver,
            db_router,
            s3_bucket,
            aws_endpoint,
        )
    )

    await asyncio.gather(transform_task, deliver_task)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
