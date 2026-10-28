"""Inbound EventEnvelope Route Registry for `ip-delivery-worker` (Layer 5 & Layer 1 External I/O)."""

from __future__ import annotations

import asyncio
import json

import structlog
from ip.engine.adapters.inbound.workers.ip_disposition import (
    IpWorkerResultDispositionHandler,
)
from ip.engine.adapters.inbound.workers.ip_payload_dtos import (
    IpFetchRecordChunkPayloadDTO,
    IpOutboundRecordChunkPayloadDTO,
    IpSyncRunRequestedPayloadDTO,
)
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordResponse,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordResultDTO,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
)
from ip.engine.application.worker_ports import (
    IpFetchRecordExecutorPort,
    IpOutboundDeliveryExecutorPort,
    IpRunSyncExecutorPort,
)
from ip.engine.domain.enums import (
    FailureDisposition,
    FetchRecordStatus,
    IpEventType,
    OutboundDispatchStatus,
    SyncErrorCode,
    SyncRunStatus,
)
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from pubsub.enums import ConsumerAction
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class IpDeliveryRouteRegistry:
    """Wires IP L5 outbound delivery and L1 external pull handlers into `EventEnvelopeDispatcher`.

    Enforces:
    - Strict PENDING-only filtering on `ip.outbound_record.created` to prevent feedback loops.
    - Consumer idempotency via `uow.record_idempotency(tenant_id, idempotency_key)`.
    - Bounded per-chunk network concurrency via `asyncio.Semaphore(max_chunk_concurrency)`.
    - First-class error disposition (`Result[T, IpError]` -> `ConsumerAction`).
    """

    def __init__(
        self,
        *,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        deliver_outbound_use_case: IpOutboundDeliveryExecutorPort,
        fetch_record_use_case: IpFetchRecordExecutorPort,
        run_sync_use_case: IpRunSyncExecutorPort,
        tiered_storage: TieredStoragePort | None = None,
        max_chunk_concurrency: int = 10,
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._deliver_outbound = deliver_outbound_use_case
        self._fetch_record = fetch_record_use_case
        self._run_sync = run_sync_use_case
        self._tiered_storage = tiered_storage
        self._max_chunk_concurrency = max(1, max_chunk_concurrency)

    def register_routes(self, dispatcher: EventEnvelopeDispatcher) -> None:
        """Subscribes all IP Layer 5 and Layer 1 external I/O handlers on `dispatcher`."""
        dispatcher.subscribe(
            IpEventType.OUTBOUND_RECORD_CREATED.value,
            self.handle_outbound_record_created,
        )
        dispatcher.subscribe(
            IpEventType.FETCH_RECORD_REQUESTED.value,
            self.handle_fetch_record_requested,
        )
        dispatcher.subscribe(
            IpEventType.SYNC_RUN_REQUESTED.value,
            self.handle_sync_run_requested,
        )

    async def handle_outbound_record_created(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpOutboundRecordChunkPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        # Only PENDING outbound records require execution (ignore DELIVERED/FAILED updates)
        if dto.status != OutboundDispatchStatus.PENDING.value:
            logger.info(
                "ip_delivery_non_pending_envelope_skipped",
                event_id=envelope.id,
                tenant_id=dto.tenant_id,
                status=dto.status,
            )
            return ConsumerAction.ACK

        shard_res = await self._dp_uow_provider.resolve_shard_info(dto.tenant_id)
        if shard_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, shard_res)
        shard_id, shard_dsn = shard_res.unwrap()

        if envelope.idempotency_key:
            async with self._dp_uow_provider.get_data_plane_uow(
                dto.tenant_id, shard_id, shard_dsn
            ) as idem_uow:
                claimed = await idem_uow.record_idempotency(dto.tenant_id, envelope.idempotency_key)
                if not claimed:
                    logger.info(
                        "ip_delivery_duplicate_envelope_skipped",
                        event_id=envelope.id,
                        event_type=envelope.event_type,
                        idempotency_key=envelope.idempotency_key,
                        tenant_id=dto.tenant_id,
                    )
                    return ConsumerAction.ACK
                await idem_uow.commit()

        sem = asyncio.Semaphore(self._max_chunk_concurrency)
        outcomes = await asyncio.gather(
            *(
                self._deliver_single_record(
                    sem=sem,
                    tenant_id=dto.tenant_id,
                    shard_id=shard_id,
                    shard_dsn=shard_dsn,
                    outbound_record_id=rec_id,
                )
                for rec_id in dto.record_ids
            )
        )
        action = IpWorkerResultDispositionHandler.to_chunk_consumer_action(envelope, outcomes)
        if action is ConsumerAction.NACK and envelope.idempotency_key:
            async with self._dp_uow_provider.get_data_plane_uow(
                dto.tenant_id, shard_id, shard_dsn
            ) as release_uow:
                await release_uow.release_idempotency(dto.tenant_id, envelope.idempotency_key)
                await release_uow.commit()
            logger.info(
                "ip_delivery_idempotency_released_on_nack",
                event_id=envelope.id,
                event_type=envelope.event_type,
                idempotency_key=envelope.idempotency_key,
                tenant_id=dto.tenant_id,
            )
        return action

    async def _deliver_single_record(
        self,
        *,
        sem: asyncio.Semaphore,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
        outbound_record_id: str,
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        async with sem:
            async with self._dp_uow_provider.get_data_plane_uow(
                tenant_id, shard_id, shard_dsn
            ) as uow:
                staged = await uow.outbound_records.get_by_id(
                    record_id=outbound_record_id,
                    tenant_id=tenant_id,
                )
            if staged is None:
                return Result.err(
                    IpError(
                        code=IpErrorCode.VALIDATION_FAILED,
                        message=f"OutboundRecord '{outbound_record_id}' not found for tenant '{tenant_id}'.",
                        details={"outbound_record_id": outbound_record_id},
                        disposition=FailureDisposition.FAIL,
                    )
                )
            if staged.status is OutboundDispatchStatus.DELIVERED:
                logger.info(
                    "ip_delivery_already_delivered_record_skipped",
                    outbound_record_id=staged.id,
                    tenant_id=tenant_id,
                    trace_id=staged.trace_id,
                )
                return Result.ok(
                    DeliverOutboundRecordResponse(
                        outbound_record_id=staged.id,
                        status=OutboundDispatchStatus.DELIVERED,
                        trace_id=staged.trace_id,
                        idempotency_key=staged.idempotency_key or staged.id,
                        record_id=staged.external_record_id or staged.id,
                        destination_id=staged.external_record_id,
                        response_status_code=staged.response_status_code,
                        response_body=staged.response_body,
                        response_s3_key=staged.response_s3_key,
                        duration_ms=staged.duration_ms,
                        was_deduplicated=True,
                    )
                )

            payload_res = await self._hydrate_outbound_payload(staged)
            if payload_res.is_err:
                return Result.err(payload_res.unwrap_err())

            headers_map: dict[str, str] = {
                str(k): str(v) for k, v in staged.request_headers.items()
            }
            delivery_res = await self._deliver_outbound.execute(
                DeliverOutboundRecordCommand(
                    tenant_id=staged.tenant_id,
                    connection_id=staged.connection_id,
                    stream_name=staged.stream_name,
                    operation=staged.operation,
                    payload=payload_res.unwrap(),
                    record_id=staged.external_record_id,
                    idempotency_key=staged.idempotency_key or staged.id,
                    headers=headers_map,
                    trace_id=staged.trace_id,
                    correlation_id=staged.correlation_id,
                    parent_trace_id=staged.parent_trace_id,
                    original_trace_id=staged.original_trace_id,
                    replay_count=staged.replay_count,
                    attempt_number=staged.attempt_number,
                )
            )
            if delivery_res.is_err:
                return delivery_res
            return IpWorkerResultDispositionHandler.map_outbound_response(delivery_res.unwrap())

    async def _hydrate_outbound_payload(self, staged: OutboundRecord) -> Result[JsonDict, IpError]:
        if staged.request_body is not None:
            return Result.ok(dict(staged.request_body))
        if staged.request_s3_key is not None:
            if self._tiered_storage is None:
                return Result.err(
                    IpError(
                        code=IpErrorCode.PAYLOAD_NOT_FOUND,
                        message=f"TieredStoragePort required to hydrate S3 payload '{staged.request_s3_key}'.",
                        disposition=FailureDisposition.FAIL,
                    )
                )
            retrieved = await self._tiered_storage.retrieve(
                TieredStorageResultDTO(
                    is_inlined=False,
                    raw_payload=None,
                    s3_key=staged.request_s3_key,
                    payload_size_bytes=staged.request_size_bytes,
                    payload_sha256=staged.request_sha256,
                )
            )
            if retrieved.is_err or retrieved.value is None:
                return Result.err(
                    IpError(
                        code=IpErrorCode.PAYLOAD_NOT_FOUND,
                        message=f"Failed to retrieve S3 payload '{staged.request_s3_key}'.",
                        disposition=FailureDisposition.RETRY,
                    )
                )
            try:
                loaded = json.loads(retrieved.value.decode("utf-8"))
                if isinstance(loaded, dict):
                    return Result.ok(loaded)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            return Result.err(
                IpError(
                    code=IpErrorCode.PAYLOAD_NOT_FOUND,
                    message=f"Corrupt S3 payload for OutboundRecord '{staged.id}'.",
                    disposition=FailureDisposition.FAIL,
                )
            )
        return Result.ok({})

    async def handle_fetch_record_requested(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpFetchRecordChunkPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        sem = asyncio.Semaphore(self._max_chunk_concurrency)

        async def _fetch_one(record_id: str) -> Result[FetchRecordResultDTO, IpError]:
            async with sem:
                res = await self._fetch_record.execute(
                    FetchRecordCommand(
                        tenant_id=dto.tenant_id,
                        connection_id=dto.connection_id,
                        stream_name=dto.stream_name,
                        record_id=record_id,
                        trace_id=dto.trace_id,
                        correlation_id=dto.correlation_id,
                    )
                )
                if res.status in (
                    FetchRecordStatus.FETCHED.value,
                    FetchRecordStatus.DEDUPLICATED.value,
                    FetchRecordStatus.NOT_FOUND.value,
                ):
                    return Result.ok(res)
                if res.status in (
                    FetchRecordStatus.RATE_LIMITED.value,
                    FetchRecordStatus.TRANSIENT_ERROR.value,
                    FetchRecordStatus.FETCH_FAILED.value,
                ):
                    return Result.err(
                        IpError(
                            code=IpErrorCode.EXTERNAL_API_ERROR,
                            message=f"FetchRecord transient failure ({res.status}) for '{record_id}'.",
                            disposition=FailureDisposition.RETRY,
                        )
                    )
                return Result.err(
                    IpError(
                        code=IpErrorCode.EXTERNAL_API_ERROR,
                        message=f"FetchRecord terminal failure ({res.status}) for '{record_id}'.",
                        disposition=FailureDisposition.FAIL,
                    )
                )

        outcomes = await asyncio.gather(*(_fetch_one(rec_id) for rec_id in dto.record_ids))
        return IpWorkerResultDispositionHandler.to_chunk_consumer_action(envelope, outcomes)

    async def handle_sync_run_requested(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpSyncRunRequestedPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        res = await self._run_sync.execute(
            RunSyncCommand(
                tenant_id=dto.tenant_id,
                connection_id=dto.connection_id,
                stream_name=dto.stream_name,
                forced_kind=dto.forced_kind,
                trace_id=dto.trace_id,
                correlation_id=dto.correlation_id,
            )
        )
        if res.status in (
            SyncRunStatus.SUCCEEDED.value,
            SyncRunStatus.SKIPPED_ALREADY_ACTIVE.value,
        ):
            return ConsumerAction.ACK

        if res.error_code in (
            SyncErrorCode.RATE_LIMITED.value,
            SyncErrorCode.TRANSIENT_ERROR.value,
            SyncErrorCode.UPSTREAM_5XX.value,
        ):
            return IpWorkerResultDispositionHandler.to_consumer_action(
                envelope,
                Result.err(
                    IpError(
                        code=IpErrorCode.EXTERNAL_API_ERROR,
                        message=res.error_message or "Sync run transient failure.",
                        disposition=FailureDisposition.RETRY,
                    )
                ),
            )

        return IpWorkerResultDispositionHandler.to_consumer_action(
            envelope,
            Result.err(
                IpError(
                    code=IpErrorCode.EXTERNAL_API_ERROR,
                    message=res.error_message or f"Sync run failed ({res.error_code}).",
                    disposition=FailureDisposition.FAIL,
                )
            ),
        )


__all__ = [
    "IpDeliveryRouteRegistry",
    "IpFetchRecordExecutorPort",
    "IpOutboundDeliveryExecutorPort",
    "IpRunSyncExecutorPort",
]
