"""Use case for Layer 2 Universal Replica extraction, deduplication, and atomic ledger commit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from ip.engine.domain.enums import MergeOutcome
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.models.replica_record import (
    ReplicaRejection,
    compute_data_hash,
    compute_record_key,
)
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.record_extractor_port import (
    DEFAULT_EXTRACTOR_REGISTRY,
    RecordExtractorRegistry,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaMergeCandidate
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort, TieredStorageResultDTO
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort, DataPlaneUnitOfWorkPort
from seedwork.domain.types import JsonValue
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReplicateRecordsCommand:
    """Command payload to extract and merge records into Layer 2 Universal Replica ledger."""

    tenant_id: str
    connection_id: str
    stream: str
    inbound_record_id: str
    generation_id: int
    sync_id: str
    trace_id: str
    correlation_id: str | None = None
    next_checkpoint: str | None = None
    raw_payload: JsonValue = None
    stream_definition: StreamDefinition | None = None


@dataclass(frozen=True)
class ReplicationSummary:
    """Summary of replication results for a chunk."""

    inserted_count: int
    updated_count: int
    noop_count: int
    stale_count: int
    tombstone_count: int
    rejected_count: int


class ReplicateRecordsUseCase:
    """Universal L2 replication coordinator extracting records, merging snapshots, and logging rejections."""

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        extractor_registry: RecordExtractorRegistry | None = None,
        control_plane_uow: ControlPlaneUnitOfWorkPort | None = None,
        tiered_storage: TieredStoragePort | None = None,
    ) -> None:
        self._uow = uow
        self._extractor_registry = extractor_registry or DEFAULT_EXTRACTOR_REGISTRY
        self._control_plane_uow = control_plane_uow
        self._tiered_storage = tiered_storage

    async def _resolve_raw_payload(self, command: ReplicateRecordsCommand) -> JsonValue:
        if command.raw_payload is not None:
            return command.raw_payload
        inbound = await self._uow.inbound_records.get_by_id(
            record_id=command.inbound_record_id,
            tenant_id=command.tenant_id,
        )
        if inbound is None:
            return {}
        if inbound.request_body is not None:
            return inbound.request_body
        if inbound.request_s3_key is not None and self._tiered_storage is not None:
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
                    return parsed
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return {}
        return {}

    async def execute(
        self, command: ReplicateRecordsCommand
    ) -> Result[ReplicationSummary, IpError]:
        # 1. Resolve raw payload
        raw_payload = await self._resolve_raw_payload(command)

        # 2. Resolve stream definition
        stream_def = command.stream_definition or StreamDefinition(
            stream=command.stream,
            primary_key=(("id",),),
        )

        # 3. Resolve extractor and run pure extraction
        extractor = self._extractor_registry.get(stream_def.extractor_id)
        batch = extractor.extract(raw_payload, stream_def)

        # 4. Assemble merge candidates
        candidates: list[ReplicaMergeCandidate] = []
        for rec in batch.records:
            record_key = compute_record_key(rec.primary_key_values)
            data_hash = compute_data_hash(rec.data)
            candidates.append(
                ReplicaMergeCandidate(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream=command.stream,
                    record_key=record_key,
                    primary_key_values=rec.primary_key_values,
                    cursor_value=str(rec.cursor_value) if rec.cursor_value is not None else None,
                    cursor_kind=stream_def.cursor_kind.value,
                    data=rec.data,
                    data_hash=data_hash,
                    generation_id=command.generation_id,
                    source_inbound_record_id=command.inbound_record_id,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    is_deleted=rec.is_deleted,
                )
            )

        # 5. Merge batch into replica ledger
        merge_results = await self._uow.replica_records.merge_batch(candidates)

        # 6. Save rejections
        rejections: list[ReplicaRejection] = []
        now = datetime.now(UTC)
        for rej in batch.rejections:
            rejections.append(
                ReplicaRejection(
                    id=generate_id("rej"),
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream=command.stream,
                    inbound_record_id=command.inbound_record_id,
                    record_index=rej.record_index,
                    reason=rej.reason.value,
                    detail=rej.detail,
                    trace_id=command.trace_id,
                    created_at=now,
                )
            )
        if rejections:
            await self._uow.replica_rejections.save_batch(rejections)

        # 7. Advance checkpoint if requested and control plane UoW available
        if command.next_checkpoint and self._control_plane_uow is not None:
            state = await self._control_plane_uow.stream_states.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream,
            )
            if state is not None:
                state.advance_checkpoint(
                    new_cursor_value=command.next_checkpoint,
                    records_in_batch=len(candidates),
                )
                await self._control_plane_uow.stream_states.save(state)

        # 8. Tally summary counts
        counts = {
            MergeOutcome.INSERT: 0,
            MergeOutcome.UPDATE: 0,
            MergeOutcome.NOOP: 0,
            MergeOutcome.STALE: 0,
            MergeOutcome.TOMBSTONE: 0,
        }
        for res in merge_results:
            counts[res.outcome] = counts.get(res.outcome, 0) + 1

        summary = ReplicationSummary(
            inserted_count=counts[MergeOutcome.INSERT],
            updated_count=counts[MergeOutcome.UPDATE],
            noop_count=counts[MergeOutcome.NOOP],
            stale_count=counts[MergeOutcome.STALE],
            tombstone_count=counts[MergeOutcome.TOMBSTONE],
            rejected_count=len(rejections),
        )

        logger.info(
            "replicate_records_chunk_completed",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            inserted=summary.inserted_count,
            updated=summary.updated_count,
            noop=summary.noop_count,
            stale=summary.stale_count,
            tombstone=summary.tombstone_count,
            rejected=summary.rejected_count,
        )

        return Result.ok(summary)
