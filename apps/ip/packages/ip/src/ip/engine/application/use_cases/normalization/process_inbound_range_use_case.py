"""Fused Layer 2 to Layer 3 single-transaction range processor.

Executes Layer 1 range claim-check retrieval, Layer 2 universal replica extraction/hash-merge,
and Layer 3 canonical normalization inside a single Data Plane ACID transaction with zero
intermediate outbox/SQS hops.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from seedwork.domain.types import JsonDict, JsonValue
from structlog.typing import FilteringBoundLogger

from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    REPLICA_MERGE_CHUNK_SIZE,
    ReplicateRecordsUseCase,
    ReplicationSummary,
)
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    IpError,
    IpErrorCode,
    PayloadNotFoundError,
    Result,
)
from ip.engine.domain.normalization.enums import NormalizationOutcome
from ip.engine.domain.normalization.event_policies import FUSED_IN_MEMORY_EVENT_POLICY
from ip.engine.domain.replication.enums import MergeOutcome
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import (
    ReplicaRejection,
    compute_data_hash,
    compute_record_key,
)
from ip.engine.domain.replication.stream_definition import StreamDefinition
from ip.engine.ports.outbound.record_extractor_port import (
    RecordExtractorPort,
    RecordExtractorRegistry,
)
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
)
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort, TieredStorageResultDTO
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)

_MUTATED_OUTCOMES = frozenset({MergeOutcome.INSERT, MergeOutcome.UPDATE, MergeOutcome.TOMBSTONE})


def _coerce_canonical_json_dict(raw: Mapping[str, JsonValue | Decimal]) -> JsonDict:
    coerced: JsonDict = {}
    for key, val in raw.items():
        coerced[key] = str(val) if isinstance(val, Decimal) else val
    return coerced


@dataclass(frozen=True)
class ProcessInboundRangeCommand:
    """Command triggering fused L2 extraction/merge and L3 normalization for an L1 range."""

    tenant_id: str
    connection_id: str
    stream: str
    batch_id: str = ""
    range_start: str = ""
    range_end: str = ""
    record_ids: tuple[str, ...] = ()
    count: int = 1
    generation_id: int = 1
    sync_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    causation_depth: int = 0
    stream_definition: StreamDefinition | None = None


@dataclass(frozen=True)
class CanonicalChangeItemDTO:
    """In-memory canonical mutation summary produced by L3 for immediate L4 Stitch evaluation."""

    canonical_type: str
    source_id: str
    action: str
    outcome: NormalizationOutcome
    replica_id: str
    replica_version: int
    transformation_id: str
    transformation_version: int
    trace_id: str = ""
    correlation_id: str | None = None
    changed_fields: tuple[str, ...] = ()
    canonical_payload: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessInboundRangeResultDTO:
    """Summary of fused L2 replication and L3 canonical normalization across an L1 range."""

    replication_summary: ReplicationSummary
    canonical_changes: tuple[CanonicalChangeItemDTO, ...] = ()
    inbound_records_processed: int = 0


class ProcessInboundRangeUseCase:
    """Co-locates L2 replica extraction/merge and L3 canonical normalization in one ACID commit."""

    def __init__(
        self,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        normalize_use_case: NormalizeReplicaRecordUseCase,
        extractor_registry: RecordExtractorRegistry | None = None,
        tiered_storage: TieredStoragePort | None = None,
    ) -> None:
        self._control_plane_uow = control_plane_uow
        self._data_plane_uow_provider = data_plane_uow_provider
        self._normalize_use_case = normalize_use_case
        self._extractor_registry = (
            extractor_registry if extractor_registry is not None else RecordExtractorRegistry()
        )
        self._tiered_storage = tiered_storage

    async def _resolve_inbound_payload(self, inbound: InboundRecord) -> Result[JsonValue, IpError]:
        if inbound.request_body is not None:
            return Result.ok(ReplicateRecordsUseCase._unwrap_inlined_body(inbound.request_body))
        if inbound.request_s3_key is not None:
            if self._tiered_storage is None:
                return Result.err(
                    PayloadNotFoundError(
                        s3_key=inbound.request_s3_key,
                        message="Tiered storage adapter is not configured to retrieve S3 payload.",
                    )
                )
            storage_dto = TieredStorageResultDTO(
                is_inlined=False,
                raw_payload=None,
                s3_key=inbound.request_s3_key,
                payload_size_bytes=inbound.request_size_bytes,
                payload_sha256=inbound.request_sha256,
            )
            retrieved = await self._tiered_storage.retrieve(storage_dto)
            if retrieved.is_ok and retrieved.value is not None:
                try:
                    parsed: JsonValue = json.loads(retrieved.value.decode("utf-8"))
                    return Result.ok(parsed)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    return Result.err(
                        PayloadNotFoundError(
                            s3_key=inbound.request_s3_key,
                            message=f"Corrupt or non-JSON S3 payload for record '{inbound.id}': {exc}",
                        )
                    )
            return Result.err(
                PayloadNotFoundError(
                    s3_key=inbound.request_s3_key,
                    message=f"Failed to retrieve S3 payload for record '{inbound.id}'.",
                )
            )
        return Result.err(
            PayloadNotFoundError(
                message=f"No inline or S3 payload present for record '{inbound.id}'."
            )
        )

    @staticmethod
    def _build_replication_summary(
        merge_results: list[MergeResult], rejections_count: int
    ) -> ReplicationSummary:
        counts = {
            MergeOutcome.INSERT: 0,
            MergeOutcome.UPDATE: 0,
            MergeOutcome.NOOP: 0,
            MergeOutcome.STALE: 0,
            MergeOutcome.TOMBSTONE: 0,
        }
        for res in merge_results:
            counts[res.outcome] = counts.get(res.outcome, 0) + 1
        return ReplicationSummary(
            inserted_count=counts[MergeOutcome.INSERT],
            updated_count=counts[MergeOutcome.UPDATE],
            noop_count=counts[MergeOutcome.NOOP],
            stale_count=counts[MergeOutcome.STALE],
            tombstone_count=counts[MergeOutcome.TOMBSTONE],
            rejected_count=rejections_count,
        )

    @staticmethod
    def _deduplicate_mutated_results(merge_results: list[MergeResult]) -> list[MergeResult]:
        deduped_by_id: dict[str, MergeResult] = {}
        for res in merge_results:
            if res.outcome in _MUTATED_OUTCOMES:
                deduped_by_id[res.record_id] = res
        return list(deduped_by_id.values())

    async def _collect_canonical_changes_for_replica(
        self,
        *,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ProcessInboundRangeCommand,
        merge_res: MergeResult,
        transformation_lookup_stream: str,
        canonical_changes_sink: list[CanonicalChangeItemDTO],
        bound_logger: FilteringBoundLogger,
    ) -> Result[None, IpError]:
        transformation = await self._control_plane_uow.transformations.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=transformation_lookup_stream,
        )
        replica = merge_res.replica
        effective_trace_id = (
            replica.trace_id if replica is not None and replica.trace_id else command.trace_id
        )
        effective_corr_id = (
            replica.correlation_id
            if replica is not None and replica.correlation_id is not None
            else command.correlation_id
        )
        norm_cmd = NormalizeReplicaRecordCommand(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=merge_res.stream,
            replica_record_id=merge_res.record_id,
            replica_version=merge_res.version,
            trace_id=effective_trace_id,
            correlation_id=effective_corr_id,
        )
        norm_res = await self._normalize_use_case.normalize_replica_in_uow(
            uow=uow,
            transformation=transformation,
            command=norm_cmd,
            replica=replica,
            event_policy=FUSED_IN_MEMORY_EVENT_POLICY,
        )
        if norm_res.is_err:
            err = norm_res.unwrap_err()
            bound_logger.error(
                "fused_l3_normalization_failed",
                replica_record_id=merge_res.record_id,
                error=err.message,
            )
            return Result.err(err)

        norm_dto = norm_res.unwrap()
        for evt in norm_dto.canonical_events:
            norm_rows = await uow.normalized_records.list_by_source(
                command.tenant_id,
                evt.canonical_type,
                evt.source_id,
                connection_id=evt.connection_id,
            )
            draft_payload = norm_dto.canonical_payloads.get((evt.canonical_type, evt.source_id), {})
            payload_dict: JsonDict = (
                _coerce_canonical_json_dict(norm_rows[0].canonical_data)
                if norm_rows
                else _coerce_canonical_json_dict(draft_payload)
            )
            canonical_changes_sink.append(
                CanonicalChangeItemDTO(
                    canonical_type=evt.canonical_type,
                    source_id=evt.source_id,
                    action=evt.action,
                    outcome=norm_dto.outcome,
                    replica_id=evt.replica_id,
                    replica_version=evt.replica_version,
                    transformation_id=evt.transformation_id,
                    transformation_version=evt.transformation_version,
                    trace_id=evt.trace_id,
                    correlation_id=evt.correlation_id,
                    changed_fields=evt.changed_fields,
                    canonical_payload=payload_dict,
                )
            )
        return Result.ok(None)

    @staticmethod
    def _validate_inbound_records(
        command: ProcessInboundRangeCommand,
        inbound_records: Sequence[InboundRecord],
        bound_logger: FilteringBoundLogger,
    ) -> Result[None, IpError]:
        if not inbound_records and (command.batch_id or command.range_start or command.record_ids):
            bound_logger.error("inbound_range_records_not_found")
            return Result.err(
                PayloadNotFoundError(
                    message=(
                        f"No inbound records found for tenant '{command.tenant_id}' "
                        f"(batch_id='{command.batch_id}', range_start='{command.range_start}')."
                    )
                )
            )

        if command.record_ids:
            found_ids = {r.id for r in inbound_records}
            missing_ids = set(command.record_ids) - found_ids
            if missing_ids:
                bound_logger.error(
                    "inbound_range_explicit_record_ids_missing",
                    missing_ids=sorted(missing_ids),
                )
                return Result.err(
                    PayloadNotFoundError(
                        message=(
                            f"Explicit record_ids missing for tenant '{command.tenant_id}': "
                            f"{sorted(missing_ids)}"
                        )
                    )
                )
        return Result.ok(None)

    @staticmethod
    async def _recover_noop_canonical_changes(
        uow: IpDataPlaneUnitOfWorkPort,
        command: ProcessInboundRangeCommand,
        merge_results: list[MergeResult],
        canonical_changes: list[CanonicalChangeItemDTO],
    ) -> None:
        for merge_res in merge_results:
            if merge_res.outcome is MergeOutcome.NOOP and merge_res.replica is not None:
                norm_rows = await uow.normalized_records.list_records(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                )
                matching = [r for r in norm_rows if r.source_id == merge_res.replica.record_key]
                for nr in matching:
                    canonical_changes.append(
                        CanonicalChangeItemDTO(
                            canonical_type=nr.canonical_type,
                            source_id=nr.source_id,
                            action="UPSERT",
                            outcome=NormalizationOutcome.NORMALIZED,
                            replica_id=merge_res.record_id,
                            replica_version=merge_res.version,
                            transformation_id="",
                            transformation_version=1,
                            trace_id=nr.trace_id,
                            correlation_id=nr.correlation_id,
                            changed_fields=(),
                            canonical_payload=_coerce_canonical_json_dict(nr.canonical_data),
                        )
                    )

    async def _extract_range_candidates(
        self,
        *,
        inbound_records: Sequence[InboundRecord],
        command: ProcessInboundRangeCommand,
        stream_def: StreamDefinition,
        extractor: RecordExtractorPort,
    ) -> Result[tuple[tuple[ReplicaMergeCandidate, ...], tuple[ReplicaRejection, ...]], IpError]:
        candidates: list[ReplicaMergeCandidate] = []
        rejections: list[ReplicaRejection] = []
        now = datetime.now(UTC)

        for inbound in inbound_records:
            if (
                inbound.connection_id != command.connection_id
                or inbound.stream_name != command.stream
            ):
                return Result.err(
                    IpError(
                        code=IpErrorCode.VALIDATION_FAILED,
                        message=(
                            f"InboundRecord '{inbound.id}' connection/stream "
                            f"('{inbound.connection_id}'/'{inbound.stream_name}') does not match "
                            f"range command ('{command.connection_id}'/'{command.stream}')."
                        ),
                        disposition=FailureDisposition.FAIL,
                    )
                )

            payload_res = await self._resolve_inbound_payload(inbound)
            if payload_res.is_err:
                return Result.err(payload_res.unwrap_err())

            extracted_batch = extractor.extract(payload_res.unwrap(), stream_def)
            rec_trace_id = inbound.trace_id or command.trace_id
            rec_corr_id = (
                inbound.correlation_id
                if inbound.correlation_id is not None
                else command.correlation_id
            )

            for extracted_rec in extracted_batch.records:
                candidates.append(
                    ReplicaMergeCandidate(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream=command.stream,
                        record_key=compute_record_key(extracted_rec.primary_key_values),
                        primary_key_values=extracted_rec.primary_key_values,
                        cursor_value=(
                            str(extracted_rec.cursor_value)
                            if extracted_rec.cursor_value is not None
                            else None
                        ),
                        cursor_kind=stream_def.cursor_kind.value,
                        data=extracted_rec.data,
                        data_hash=compute_data_hash(extracted_rec.data),
                        generation_id=command.generation_id,
                        source_inbound_record_id=inbound.id,
                        trace_id=rec_trace_id,
                        correlation_id=rec_corr_id,
                        is_deleted=extracted_rec.is_deleted,
                    )
                )

            for rej in extracted_batch.rejections:
                rejections.append(
                    ReplicaRejection.create(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream=command.stream,
                        inbound_record_id=inbound.id,
                        record_index=rej.record_index,
                        reason=rej.reason.value,
                        detail=rej.detail,
                        trace_id=rec_trace_id,
                        created_at=now,
                    )
                )
        return Result.ok((tuple(candidates), tuple(rejections)))

    async def execute(
        self, command: ProcessInboundRangeCommand
    ) -> Result[ProcessInboundRangeResultDTO, IpError]:
        """Executes L2 extraction/merge and L3 normalization inside one Data Plane transaction."""
        bound_logger: FilteringBoundLogger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            batch_id=command.batch_id,
            range_start=command.range_start,
            range_end=command.range_end,
            count=command.count,
            trace_id=command.trace_id,
        )
        bound_logger.info("fused_inbound_range_processing_started")

        shard_info_res = await self._data_plane_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_info_res.is_err:
            bound_logger.error(
                "tenant_shard_resolution_failed",
                error=shard_info_res.unwrap_err().message,
            )
            return Result.err(shard_info_res.unwrap_err())

        shard_id, shard_dsn = shard_info_res.unwrap()
        stream_def = command.stream_definition or StreamDefinition(
            stream=command.stream,
            primary_key=(("id",),),
        )
        extractor = self._extractor_registry.get(stream_def.extractor_id)

        merge_results: list[MergeResult] = []
        canonical_changes: list[CanonicalChangeItemDTO] = []

        async with self._data_plane_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            inbound_records = await uow.inbound_records.list_by_range(
                command.tenant_id,
                batch_id=command.batch_id,
                range_start=command.range_start,
                range_end=command.range_end,
                record_ids=command.record_ids,
            )
            val_res = self._validate_inbound_records(command, inbound_records, bound_logger)
            if val_res.is_err:
                return Result.err(val_res.unwrap_err())

            extracted_res = await self._extract_range_candidates(
                inbound_records=inbound_records,
                command=command,
                stream_def=stream_def,
                extractor=extractor,
            )
            if extracted_res.is_err:
                return Result.err(extracted_res.unwrap_err())
            candidates, rejections = extracted_res.unwrap()

            for idx in range(0, len(candidates), REPLICA_MERGE_CHUNK_SIZE):
                chunk = candidates[idx : idx + REPLICA_MERGE_CHUNK_SIZE]
                chunk_results = await uow.replica_records.merge_batch(
                    chunk,
                    event_policy=FUSED_IN_MEMORY_EVENT_POLICY,
                )
                merge_results.extend(chunk_results)

            if rejections:
                await uow.replica_rejections.save_batch(rejections)

            mutated_results = self._deduplicate_mutated_results(merge_results)
            if not mutated_results and merge_results:
                await self._recover_noop_canonical_changes(
                    uow=uow,
                    command=command,
                    merge_results=merge_results,
                    canonical_changes=canonical_changes,
                )
            for merge_res in mutated_results:
                step_res = await self._collect_canonical_changes_for_replica(
                    uow=uow,
                    command=command,
                    merge_res=merge_res,
                    transformation_lookup_stream=merge_res.stream,
                    canonical_changes_sink=canonical_changes,
                    bound_logger=bound_logger,
                )
                if step_res.is_err:
                    return Result.err(step_res.unwrap_err())

            await uow.commit()

        summary = self._build_replication_summary(merge_results, len(rejections))
        bound_logger.info(
            "fused_inbound_range_processing_completed",
            inbound_records_processed=len(inbound_records),
            inserted=summary.inserted_count,
            updated=summary.updated_count,
            noop=summary.noop_count,
            stale=summary.stale_count,
            tombstone=summary.tombstone_count,
            rejected=summary.rejected_count,
            canonical_changes_count=len(canonical_changes),
        )
        return Result.ok(
            ProcessInboundRangeResultDTO(
                replication_summary=summary,
                canonical_changes=tuple(canonical_changes),
                inbound_records_processed=len(inbound_records),
            )
        )
