import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
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

from worker.adapters.aws_secrets_manager import AwsSecretsManagerSecretStore
from worker.core.security import ssrf_safe_context
from worker.core.tenant_resolver import TenantResolver

logger = structlog.get_logger(__name__)


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
                            "Skipping duplicate event with idempotency_key={idempotency_key}",
                            idempotency_key=idempotency_key,
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
                    logger.info("[WORKER] Transforming trace_id={trace_id}", trace_id=trace_id)

                    await service.transform(trace_id)
                    logger.info(
                        "[WORKER] SUCCESS transforming trace_id={trace_id}", trace_id=trace_id
                    )

                # Commit transaction
                await session.commit()
            except Exception:
                logger.exception(
                    "[WORKER] FAILURE in process_transformation for trace_id=%s", trace_id
                )
                await session.rollback()
                raise


async def _claim_delivery_outbox_event(session: Any, key_str: str) -> str | None:
    owner_token = str(uuid.uuid4())
    now = datetime.now(UTC)
    lease_expires = now + timedelta(minutes=5)

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
        return None
    return owner_token


async def _mark_delivery_success(session: Any, key_str: str, owner_token: str) -> None:
    from sqlalchemy.dialects.postgresql import insert

    result = await session.execute(
        update(DataPlaneOutbox)
        .where(
            DataPlaneOutbox.idempotency_key == key_str,
            DataPlaneOutbox.owner_token == owner_token,
        )
        .values(status="PROCESSED", owner_token=None, lease_expires_at=None)
    )
    if result.rowcount > 0:
        await session.execute(
            insert(ProcessedEvent).values(idempotency_key=key_str).on_conflict_do_nothing()
        )
    else:
        logger.warning(
            "[WORKER] Stale success update for idempotency_key={key_str}. Lease lost.",
            key_str=key_str,
        )


async def _mark_delivery_failure(session: Any, key_str: str, owner_token: str) -> None:
    result = await session.execute(
        update(DataPlaneOutbox)
        .where(
            DataPlaneOutbox.idempotency_key == key_str,
            DataPlaneOutbox.owner_token == owner_token,
        )
        .values(status="FAILED", owner_token=None, lease_expires_at=None)
    )
    if result.rowcount == 0:
        logger.warning("[WORKER] Stale fail update for {key_str}. Lease lost.", key_str=key_str)


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
    owner_token: str | None = None

    if key_str:
        async with contextlib.aclosing(
            db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                owner_token = await _claim_delivery_outbox_event(session, key_str)
                if not owner_token:
                    logger.info(
                        "Skipping delivery for idempotency_key={idempotency_key} (already processed or currently leased)",
                        idempotency_key=idempotency_key,
                    )
                    await session.commit()
                    return
                await session.commit()

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
                vault_adapter = AwsSecretsManagerSecretStore()
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

                if key_str and owner_token:
                    await _mark_delivery_success(session, key_str, owner_token)

                # Commit transaction
                await session.commit()
            except Exception:
                if key_str and owner_token:
                    try:
                        await session.rollback()
                        await _mark_delivery_failure(session, key_str, owner_token)
                        await session.commit()
                    except Exception:
                        logger.exception("Failed to mark outbox as FAILED")
                logger.exception("[WORKER] FAILURE in process_delivery for trace_id=%s", trace_id)
                raise
