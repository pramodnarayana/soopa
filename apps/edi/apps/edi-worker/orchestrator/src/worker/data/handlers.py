import contextlib
import logging
from typing import Any

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models.data_plane import DataPlaneOutbox, ProcessedEvent
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
from sqlalchemy import select, update

from worker.adapters.vault import WorkerVaultAdapter
from worker.core.security import ssrf_safe_context
from worker.core.tenant_resolver import TenantResolver

logger = logging.getLogger(__name__)


async def process_pipeline_event(
    trace_id: str,
    event_type: str,
    payload: dict[str, Any],
    tenant_id: str,
    resolver: TenantResolver,
    db_router: DatabaseRouter,
    s3_bucket: str,
    aws_endpoint: str | None,
    idempotency_key: str | None = None,
) -> None:
    """Sets up the Hexagonal dependencies and executes TransformService or Saga Coordinator."""
    shard_name, shard_dsn = await resolver.resolve(tenant_id)
    key_str = str(idempotency_key) if idempotency_key else None

    async with contextlib.aclosing(
        db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
    ) as session_gen:
        async for session in session_gen:
            try:
                storage_adapter = S3StorageAdapter(bucket_name=s3_bucket, endpoint_url=aws_endpoint)
                repo_adapter = SqlAlchemyRepositoryAdapter(
                    session=session,
                    settings=get_settings(),
                    storage=storage_adapter,
                )
                transformer_adapter = BotsTransformerAdapter()

                if key_str:
                    # Check for duplicate
                    stmt = select(ProcessedEvent).where(ProcessedEvent.idempotency_key == key_str)
                    existing = await session.execute(stmt)
                    if existing.scalar_one_or_none():
                        logger.info(
                            f"Skipping duplicate event with idempotency_key={idempotency_key}"
                        )
                        await session.commit()
                        return

                    # Mark as processed in same transaction
                    session.add(ProcessedEvent(idempotency_key=key_str))
                    await session.execute(
                        update(DataPlaneOutbox)
                        .where(DataPlaneOutbox.idempotency_key == key_str)
                        .values(status="PROCESSED")
                    )

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
                    logger.info(f"[WORKER] Transforming trace_id={trace_id}")

                    await service.transform(trace_id)
                    logger.info(f"[WORKER] SUCCESS transforming trace_id={trace_id}")

                # Commit transaction
                await session.commit()
            except Exception as e:
                logger.error(
                    f"[WORKER] FAILURE in process_transformation for trace_id={trace_id}: {e}"
                )
                await session.rollback()
                raise


async def process_delivery(
    trace_id: str,
    event_type: str,
    payload: dict[str, Any],
    tenant_id: str,
    resolver: TenantResolver,
    db_router: DatabaseRouter,
    s3_bucket: str,
    aws_endpoint: str | None,
    idempotency_key: str | None = None,
) -> None:
    """Sets up the Hexagonal dependencies and executes DeliveryService."""
    shard_name, shard_dsn = await resolver.resolve(tenant_id)
    key_str = str(idempotency_key) if idempotency_key else None

    # Unit of Work 1: Persist DELIVERING state before network I/O
    if key_str:
        async with contextlib.aclosing(
            db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                # Check for duplicate
                stmt = select(ProcessedEvent).where(ProcessedEvent.idempotency_key == key_str)
                existing = await session.execute(stmt)
                if existing.scalar_one_or_none():
                    logger.info(
                        f"Skipping duplicate delivery event with idempotency_key={idempotency_key}"
                    )
                    await session.commit()
                    return

                # Check Outbox status
                stmt_outbox = select(DataPlaneOutbox).where(
                    DataPlaneOutbox.idempotency_key == key_str
                )
                outbox_record = (await session.execute(stmt_outbox)).scalar_one_or_none()
                if outbox_record:
                    if outbox_record.status == "DELIVERING":
                        logger.warning(
                            f"Delivery {key_str} is in DELIVERING state (crash/timeout). Proceeding with retry downstream..."
                        )
                    elif outbox_record.status == "PROCESSED":
                        await session.commit()
                        return

                # Persist "DELIVERING" state
                await session.execute(
                    update(DataPlaneOutbox)
                    .where(DataPlaneOutbox.idempotency_key == key_str)
                    .values(status="DELIVERING")
                )
                await session.commit()

    # Unit of Work 2: Execute network delivery and persist outcome
    async with contextlib.aclosing(
        db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
    ) as session_gen:
        async for session in session_gen:
            try:
                storage_adapter = S3StorageAdapter(bucket_name=s3_bucket, endpoint_url=aws_endpoint)
                repo_adapter = SqlAlchemyRepositoryAdapter(
                    session=session,
                    settings=get_settings(),
                    storage=storage_adapter,
                )
                http_adapter = HttpxDeliveryAdapter(validator=ssrf_safe_context)
                sftp_adapter = ParamikoSftpDeliveryAdapter()
                vault_adapter = WorkerVaultAdapter()
                as2_adapter = HttpxAS2DeliveryAdapter(validator=ssrf_safe_context)

                strategies = {
                    "webhook_id": WebhookDeliveryStrategy(
                        repo_adapter, http_adapter, vault_adapter
                    ),
                    "sftp_partner_id": SftpDeliveryStrategy(
                        repo_adapter, sftp_adapter, vault_adapter
                    ),
                    "as2_partner_id": As2DeliveryStrategy(repo_adapter, as2_adapter, vault_adapter),
                }
                service = DeliveryRouter(
                    repository=repo_adapter,
                    strategies=strategies,
                )

                # Execute pure domain logic
                await service.deliver(trace_id, idempotency_key=key_str)

                if key_str:
                    session.add(ProcessedEvent(idempotency_key=key_str))
                    await session.execute(
                        update(DataPlaneOutbox)
                        .where(DataPlaneOutbox.idempotency_key == key_str)
                        .values(status="PROCESSED")
                    )
                # Commit transaction
                await session.commit()
            except Exception as delivery_error:
                if key_str:
                    try:
                        await session.rollback()
                        await session.execute(
                            update(DataPlaneOutbox)
                            .where(DataPlaneOutbox.idempotency_key == key_str)
                            .values(status="FAILED")
                        )
                        await session.commit()
                    except Exception as bookkeeping_error:
                        logger.error(
                            f"[WORKER] Failed to update outbox status after delivery error: {bookkeeping_error}"
                        )
                raise delivery_error
