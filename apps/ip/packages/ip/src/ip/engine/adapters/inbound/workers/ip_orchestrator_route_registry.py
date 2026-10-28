"""Inbound EventEnvelope Route Registry for `ip-orchestrator-worker` (Layers 2, 3, and 4)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal

import structlog
from ip.engine.adapters.inbound.workers.ip_disposition import (
    IpWorkerResultDispositionHandler,
)
from ip.engine.adapters.inbound.workers.ip_payload_dtos import (
    IpCanonicalRecordChunkPayloadDTO,
    IpGenerationCompletedPayloadDTO,
    IpInboundRecordChunkPayloadDTO,
    IpNormalizedRecordChunkPayloadDTO,
    IpReplicaRecordChunkPayloadDTO,
    IpStreamBackfillPayloadDTO,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
)
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicateRecordsCommand,
    ReplicateRecordsUseCase,
    ReplicationSummary,
)
from ip.engine.application.use_cases.replication.sweep_stale_replicas_use_case import (
    SweepStaleReplicasCommand,
    SweepStaleReplicasSummary,
    SweepStaleReplicasUseCase,
)
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
)
from ip.engine.application.worker_ports import (
    IpBackfillStreamNormalizationExecutorPort,
    IpNormalizeReplicaExecutorPort,
    IpStitchCanonicalDispatcherPort,
    IpStitchWorkerTickExecutorPort,
    IpStreamDefinitionResolver,
)
from ip.engine.domain.enums import FailureDisposition, IpEventType
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.record_extractor_port import RecordExtractorRegistry
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from orchestration.domain.exceptions import WorkflowError
from pubsub.enums import ConsumerAction
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


def _sanitize_json_dict(raw: dict[str, JsonValue | Decimal]) -> JsonDict:
    sanitized: JsonDict = {}
    for k, v in raw.items():
        if isinstance(v, Decimal):
            sanitized[k] = str(v)
        else:
            sanitized[k] = v
    return sanitized


def _workflow_error_to_ip_error(err: WorkflowError) -> IpError:
    return IpError(
        code=IpErrorCode.INTERNAL_ERROR,
        message=err.message,
        details=dict(err.details),
        disposition=FailureDisposition.FAIL,
    )


class IpOrchestratorRouteRegistry:
    """Wires IP L2, L3, and L4 chunk-pointer event handlers into `EventEnvelopeDispatcher`.

    Enforces:
    - Consumer idempotency via `uow.record_idempotency(tenant_id, idempotency_key)`.
    - Bounded per-chunk concurrency via `asyncio.Semaphore(max_chunk_concurrency)`.
    - First-class error disposition (`Result[T, IpError]` -> `ConsumerAction`).
    """

    def __init__(
        self,
        *,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        normalize_use_case: IpNormalizeReplicaExecutorPort,
        backfill_use_case: IpBackfillStreamNormalizationExecutorPort,
        extractor_registry: RecordExtractorRegistry | None = None,
        tiered_storage: TieredStoragePort | None = None,
        stitch_dispatcher: IpStitchCanonicalDispatcherPort | None = None,
        stitch_worker_tick: IpStitchWorkerTickExecutorPort | None = None,
        stream_definition_resolver: IpStreamDefinitionResolver | None = None,
        max_chunk_concurrency: int = 20,
        worker_id: str = "ip-orchestrator-worker",
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._normalize_use_case = normalize_use_case
        self._backfill_use_case = backfill_use_case
        self._extractor_registry = extractor_registry or RecordExtractorRegistry()
        self._tiered_storage = tiered_storage
        self._stitch_dispatcher = stitch_dispatcher
        self._stitch_worker_tick = stitch_worker_tick
        self._stream_definition_resolver = stream_definition_resolver
        self._max_chunk_concurrency = max(1, max_chunk_concurrency)
        self._worker_id = worker_id

    def register_routes(self, dispatcher: EventEnvelopeDispatcher) -> None:
        """Subscribes all IP Layer 2, Layer 3, and Layer 4 handlers on `dispatcher`."""
        dispatcher.subscribe(
            IpEventType.INBOUND_RECORD_CREATED.value,
            self.handle_inbound_record_created,
        )
        dispatcher.subscribe(
            IpEventType.REPLICA_RECORD_CHANGED.value,
            self.handle_replica_record_changed,
        )
        dispatcher.subscribe(
            IpEventType.CANONICAL_RECORD_CHANGED.value,
            self.handle_canonical_record_changed,
        )
        dispatcher.subscribe(
            IpEventType.NORMALIZED_RECORD_CREATED.value,
            self.handle_normalized_record_created,
        )
        dispatcher.subscribe(
            IpEventType.TRANSFORMATION_CHANGED.value,
            self.handle_stream_backfill_requested,
        )
        dispatcher.subscribe(
            IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
            self.handle_stream_backfill_requested,
        )
        dispatcher.subscribe(
            IpEventType.GENERATION_COMPLETED.value,
            self.handle_generation_completed,
        )

    async def _run_with_idempotency(
        self,
        envelope: EventEnvelope,
        tenant_id: str,
        fn: Callable[[str, str], asyncio.Future[ConsumerAction] | object],
    ) -> ConsumerAction:
        shard_res = await self._dp_uow_provider.resolve_shard_info(tenant_id)
        if shard_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, shard_res)
        shard_id, shard_dsn = shard_res.unwrap()

        if envelope.idempotency_key:
            async with self._dp_uow_provider.get_data_plane_uow(
                tenant_id, shard_id, shard_dsn
            ) as idem_uow:
                claimed = await idem_uow.record_idempotency(tenant_id, envelope.idempotency_key)
                if not claimed:
                    logger.info(
                        "ip_orchestrator_duplicate_envelope_skipped",
                        event_id=envelope.id,
                        event_type=envelope.event_type,
                        idempotency_key=envelope.idempotency_key,
                        tenant_id=tenant_id,
                    )
                    return ConsumerAction.ACK
                await idem_uow.commit()

        try:
            action = await self._invoke_chunk_fn(fn, shard_id, shard_dsn)
        except (Exception, asyncio.CancelledError):
            if envelope.idempotency_key:
                async with self._dp_uow_provider.get_data_plane_uow(
                    tenant_id, shard_id, shard_dsn
                ) as release_uow:
                    await release_uow.release_idempotency(tenant_id, envelope.idempotency_key)
                    await release_uow.commit()
                logger.info(
                    "ip_orchestrator_idempotency_released_on_exception",
                    event_id=envelope.id,
                    event_type=envelope.event_type,
                    idempotency_key=envelope.idempotency_key,
                    tenant_id=tenant_id,
                )
            raise

        if action is ConsumerAction.NACK and envelope.idempotency_key:
            async with self._dp_uow_provider.get_data_plane_uow(
                tenant_id, shard_id, shard_dsn
            ) as release_uow:
                await release_uow.release_idempotency(tenant_id, envelope.idempotency_key)
                await release_uow.commit()
            logger.info(
                "ip_orchestrator_idempotency_released_on_nack",
                event_id=envelope.id,
                event_type=envelope.event_type,
                idempotency_key=envelope.idempotency_key,
                tenant_id=tenant_id,
            )
        return action

    @staticmethod
    async def _invoke_chunk_fn(
        fn: Callable[[str, str], object],
        shard_id: str,
        shard_dsn: str,
    ) -> ConsumerAction:
        coro = fn(shard_id, shard_dsn)
        if asyncio.iscoroutine(coro):
            res: ConsumerAction = await coro
            return res
        return ConsumerAction.ACK

    async def handle_inbound_record_created(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpInboundRecordChunkPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        async def _execute_chunk(shard_id: str, shard_dsn: str) -> ConsumerAction:
            sem = asyncio.Semaphore(self._max_chunk_concurrency)
            stream_def = (
                self._stream_definition_resolver(dto.tenant_id, dto.connection_id, dto.stream_name)
                if self._stream_definition_resolver is not None
                else None
            )

            async def _replicate_one(
                inbound_record_id: str,
            ) -> Result[ReplicationSummary, IpError]:
                async with (
                    sem,
                    self._dp_uow_provider.get_data_plane_uow(
                        dto.tenant_id, shard_id, shard_dsn
                    ) as uow,
                ):
                    use_case = ReplicateRecordsUseCase(
                        uow=uow,
                        extractor_registry=self._extractor_registry,
                        tiered_storage=self._tiered_storage,
                    )
                    return await use_case.execute(
                        ReplicateRecordsCommand(
                            tenant_id=dto.tenant_id,
                            connection_id=dto.connection_id,
                            stream=dto.stream_name,
                            inbound_record_id=inbound_record_id,
                            generation_id=dto.generation_id,
                            sync_id=dto.sync_run_id or inbound_record_id,
                            trace_id=dto.trace_id,
                            correlation_id=dto.correlation_id,
                            stream_definition=stream_def,
                        )
                    )

            outcomes = await asyncio.gather(*(_replicate_one(rec_id) for rec_id in dto.record_ids))
            return IpWorkerResultDispositionHandler.to_chunk_consumer_action(envelope, outcomes)

        return await self._run_with_idempotency(envelope, dto.tenant_id, _execute_chunk)

    async def handle_replica_record_changed(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpReplicaRecordChunkPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        async def _execute_chunk(_shard_id: str, _shard_dsn: str) -> ConsumerAction:
            sem = asyncio.Semaphore(self._max_chunk_concurrency)

            async def _normalize_one(
                replica_record_id: str,
            ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
                async with sem:
                    return await self._normalize_use_case.execute(
                        NormalizeReplicaRecordCommand(
                            tenant_id=dto.tenant_id,
                            connection_id=dto.connection_id,
                            stream=dto.stream,
                            replica_record_id=replica_record_id,
                            replica_version=dto.version,
                            trace_id=dto.trace_id,
                            correlation_id=dto.correlation_id,
                            parent_trace_id=dto.parent_trace_id,
                            original_trace_id=dto.original_trace_id,
                            replay_count=dto.replay_count,
                        )
                    )

            outcomes = await asyncio.gather(*(_normalize_one(rep_id) for rep_id in dto.record_ids))
            return IpWorkerResultDispositionHandler.to_chunk_consumer_action(envelope, outcomes)

        return await self._run_with_idempotency(envelope, dto.tenant_id, _execute_chunk)

    async def handle_canonical_record_changed(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpCanonicalRecordChunkPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        if self._stitch_dispatcher is None:
            logger.info(
                "ip_orchestrator_canonical_event_skipped_no_stitch_dispatcher",
                event_id=envelope.id,
                tenant_id=dto.tenant_id,
                canonical_type=dto.canonical_type,
            )
            return ConsumerAction.ACK

        async def _execute_chunk(shard_id: str, shard_dsn: str) -> ConsumerAction:
            sem = asyncio.Semaphore(self._max_chunk_concurrency)
            dispatcher = self._stitch_dispatcher
            assert dispatcher is not None

            async def _dispatch_one(
                source_id: str,
            ) -> Result[DispatchCanonicalEventResultDTO, IpError]:
                async with sem:
                    payload_data = await self._load_canonical_payload_by_source(
                        tenant_id=dto.tenant_id,
                        shard_id=shard_id,
                        shard_dsn=shard_dsn,
                        canonical_type=dto.canonical_type,
                        source_id=source_id,
                        fallback_payload=envelope.payload,
                    )
                    res = await dispatcher.execute(
                        DispatchCanonicalEventToStitchesCommand(
                            tenant_id=dto.tenant_id,
                            canonical_event_type=dto.canonical_type,
                            event_id=f"{envelope.id}:{source_id}",
                            payload=payload_data,
                            trace_id=dto.trace_id,
                            correlation_id=dto.correlation_id,
                        )
                    )
                    if res.is_err:
                        return Result.err(_workflow_error_to_ip_error(res.unwrap_err()))
                    return Result.ok(res.unwrap())

            outcomes = await asyncio.gather(*(_dispatch_one(src_id) for src_id in dto.record_ids))
            action = IpWorkerResultDispositionHandler.to_chunk_consumer_action(envelope, outcomes)
            if action is ConsumerAction.ACK and self._stitch_worker_tick is not None:
                has_ready_steps = any(
                    r.is_ok
                    and r.value is not None
                    and (r.value.started_run_ids or r.value.signalled_step_ids)
                    for r in outcomes
                )
                if has_ready_steps:
                    await self._drain_inline_stitch_ticks()
            return action

        return await self._run_with_idempotency(envelope, dto.tenant_id, _execute_chunk)

    async def handle_normalized_record_created(self, envelope: EventEnvelope) -> ConsumerAction:
        """Handles `ip.normalized_record.created`.

        For normal normalization (`replay_count == 0`), `ip.canonical_record.changed` already
        triggers L4 Stitches, so this event is acknowledged as an audit event.
        When an operator triggers `ReplayStage.RETRY_STITCH` (`replay_count > 0`), this handler
        dispatches the cloned `NormalizedRecord` directly into L4 Stitches.
        """
        parsed_res = IpNormalizedRecordChunkPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        if dto.replay_count == 0 or self._stitch_dispatcher is None:
            logger.info(
                "ip_orchestrator_normalized_audit_event_acknowledged",
                event_id=envelope.id,
                tenant_id=dto.tenant_id,
                canonical_type=dto.canonical_type,
                replay_count=dto.replay_count,
            )
            return ConsumerAction.ACK

        async def _execute_chunk(shard_id: str, shard_dsn: str) -> ConsumerAction:
            sem = asyncio.Semaphore(self._max_chunk_concurrency)
            dispatcher = self._stitch_dispatcher
            assert dispatcher is not None

            async def _dispatch_replayed_one(
                norm_record_id: str,
            ) -> Result[DispatchCanonicalEventResultDTO, IpError]:
                async with sem:
                    payload_data = await self._load_canonical_payload_by_record_id(
                        tenant_id=dto.tenant_id,
                        shard_id=shard_id,
                        shard_dsn=shard_dsn,
                        record_id=norm_record_id,
                        fallback_payload=envelope.payload,
                    )
                    res = await dispatcher.execute(
                        DispatchCanonicalEventToStitchesCommand(
                            tenant_id=dto.tenant_id,
                            canonical_event_type=dto.canonical_type,
                            event_id=f"{envelope.id}:{norm_record_id}",
                            payload=payload_data,
                            trace_id=dto.trace_id,
                            correlation_id=dto.correlation_id,
                        )
                    )
                    if res.is_err:
                        return Result.err(_workflow_error_to_ip_error(res.unwrap_err()))
                    return Result.ok(res.unwrap())

            outcomes = await asyncio.gather(
                *(_dispatch_replayed_one(rec_id) for rec_id in dto.record_ids)
            )
            action = IpWorkerResultDispositionHandler.to_chunk_consumer_action(envelope, outcomes)
            if action is ConsumerAction.ACK and self._stitch_worker_tick is not None:
                await self._drain_inline_stitch_ticks()
            return action

        return await self._run_with_idempotency(envelope, dto.tenant_id, _execute_chunk)

    async def handle_stream_backfill_requested(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpStreamBackfillPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        res = await self._backfill_use_case.execute(
            BackfillStreamNormalizationCommand(
                tenant_id=dto.tenant_id,
                connection_id=dto.connection_id,
                stream=dto.stream,
                trace_id=dto.trace_id,
            )
        )
        return IpWorkerResultDispositionHandler.to_consumer_action(envelope, res)

    async def handle_generation_completed(self, envelope: EventEnvelope) -> ConsumerAction:
        parsed_res = IpGenerationCompletedPayloadDTO.from_envelope(envelope)
        if parsed_res.is_err:
            return IpWorkerResultDispositionHandler.to_consumer_action(envelope, parsed_res)
        dto = parsed_res.unwrap()

        async def _execute_sweep(shard_id: str, shard_dsn: str) -> ConsumerAction:
            async with self._dp_uow_provider.get_data_plane_uow(
                dto.tenant_id, shard_id, shard_dsn
            ) as uow:
                sweeper = SweepStaleReplicasUseCase(uow=uow)
                res: Result[SweepStaleReplicasSummary, IpError] = await sweeper.execute(
                    SweepStaleReplicasCommand(
                        tenant_id=dto.tenant_id,
                        connection_id=dto.connection_id,
                        stream=dto.stream,
                        current_generation=dto.generation_id,
                        trace_id=dto.trace_id,
                    )
                )
                return IpWorkerResultDispositionHandler.to_consumer_action(envelope, res)

        return await self._run_with_idempotency(envelope, dto.tenant_id, _execute_sweep)

    async def _load_canonical_payload_by_source(
        self,
        *,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
        canonical_type: str,
        source_id: str,
        fallback_payload: JsonDict,
    ) -> JsonDict:
        async with self._dp_uow_provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            records = await uow.normalized_records.list_by_source(
                tenant_id=tenant_id,
                canonical_type=canonical_type,
                source_id=source_id,
            )
            if records:
                latest = records[-1]
                merged = _sanitize_json_dict(latest.canonical_data)
                merged.setdefault("source_id", source_id)
                merged.setdefault("canonical_type", canonical_type)
                return merged
        merged_fallback = dict(fallback_payload)
        merged_fallback.setdefault("source_id", source_id)
        merged_fallback.setdefault("canonical_type", canonical_type)
        return merged_fallback

    async def _load_canonical_payload_by_record_id(
        self,
        *,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
        record_id: str,
        fallback_payload: JsonDict,
    ) -> JsonDict:
        async with self._dp_uow_provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            record = await uow.normalized_records.get_by_id(
                record_id=record_id,
                tenant_id=tenant_id,
            )
            if record is not None:
                merged = _sanitize_json_dict(record.canonical_data)
                merged.setdefault("source_id", record.source_id)
                merged.setdefault("canonical_type", record.canonical_type)
                return merged
        return dict(fallback_payload)

    async def _drain_inline_stitch_ticks(self, max_rounds: int = 10) -> None:
        if self._stitch_worker_tick is None:
            return
        for _ in range(max_rounds):
            tick_res = await self._stitch_worker_tick.execute(
                ExecuteStitchWorkerTickCommand(
                    worker_id=self._worker_id,
                    free_slots=self._max_chunk_concurrency,
                )
            )
            if tick_res.is_err:
                break
            dto = tick_res.unwrap()
            if not dto.completed_step_ids and not dto.failed_or_retried_step_ids:
                break


__all__ = [
    "IpBackfillStreamNormalizationExecutorPort",
    "IpNormalizeReplicaExecutorPort",
    "IpOrchestratorRouteRegistry",
    "IpStitchCanonicalDispatcherPort",
    "IpStitchWorkerTickExecutorPort",
    "IpStreamDefinitionResolver",
]
