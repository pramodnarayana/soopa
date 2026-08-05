import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
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
from sqlalchemy import or_, update

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
                    from sqlalchemy.dialects.postgresql import insert

                    # Atomically insert ProcessedEvent; if conflict, it returns nothing
                    stmt = (
                        insert(ProcessedEvent)
                        .values(idempotency_key=key_str)
                        .on_conflict_do_nothing()
                        .returning(ProcessedEvent.idempotency_key)
                    )
                    result = await session.execute(stmt)
                    if not result.scalar_one_or_none():
                        logger.info(
                            f"Skipping duplicate event with idempotency_key={idempotency_key}"
                        )
                        await session.commit()
                        return
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
            except Exception:
                logger.exception(
                    "[WORKER] FAILURE in process_transformation for trace_id=%s", trace_id
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
                owner_token = str(uuid.uuid4())
                now = datetime.now(UTC)
                lease_expires = now + timedelta(minutes=5)

                # Atomically claim the delivery row
                stmt = (
                    update(DataPlaneOutbox)
                    .where(
                        DataPlaneOutbox.idempotency_key == key_str,
                        DataPlaneOutbox.status != "PROCESSED",
                        or_(
                            DataPlaneOutbox.lease_expires_at.is_(None),
                            DataPlaneOutbox.lease_expires_at < now,
                        ),
                    )
                    .values(
                        status="DELIVERING",
                        owner_token=owner_token,
                        lease_expires_at=lease_expires,
                    )
                    .returning(DataPlaneOutbox.idempotency_key)
                )
                result = await session.execute(stmt)
                if not result.scalar_one_or_none():
                    logger.info(
                        f"Skipping delivery for idempotency_key={idempotency_key} (already processed or currently leased)"
                    )
                    await session.commit()
                    return

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
                    from sqlalchemy.dialects.postgresql import insert

                    result = await session.execute(
                        update(DataPlaneOutbox)
                        .where(
                            DataPlaneOutbox.idempotency_key == key_str,
                            DataPlaneOutbox.owner_token == owner_token,
                        )
                        .values(status="PROCESSED", owner_token=None, lease_expires_at=None)
                    )
                    if result.rowcount > 0:  # type: ignore[attr-defined]
                        await session.execute(
                            insert(ProcessedEvent)
                            .values(idempotency_key=key_str)
                            .on_conflict_do_nothing()
                        )
                    else:
                        logger.warning(
                            f"[WORKER] Stale success update for idempotency_key={key_str}. Lease lost."
                        )
                # Commit transaction
                await session.commit()
            except Exception:
                if key_str:
                    try:
                        await session.rollback()
                        result = await session.execute(
                            update(DataPlaneOutbox)
                            .where(
                                DataPlaneOutbox.idempotency_key == key_str,
                                DataPlaneOutbox.owner_token == owner_token,
                            )
                            .values(status="FAILED", owner_token=None, lease_expires_at=None)
                        )
                        if result.rowcount == 0:  # type: ignore[attr-defined]
                            logger.warning(
                                f"[WORKER] Stale failure update for idempotency_key={key_str}. Lease lost."
                            )
                        await session.commit()
                    except Exception:
                        logger.exception(
                            "[WORKER] Failed to update outbox status after delivery error"
                        )
                raise
