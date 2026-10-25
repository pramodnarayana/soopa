"""Use case for Layer 2 Universal Replica extraction, deduplication, and atomic ledger commit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from ip.engine.domain.constants import RESERVED_RAW_BYTES_KEY, WRAPPED_SCALAR_KEY
from ip.engine.domain.enums import MergeOutcome
from ip.engine.domain.exceptions import IpError, PayloadNotFoundError, Result
from ip.engine.domain.models.replica_record import (
    ReplicaRejection,
    compute_data_hash,
    compute_record_key,
)
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.record_extractor_port import RecordExtractorRegistry
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
)
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort, TieredStorageResultDTO
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from seedwork.domain.types import JsonValue

logger = structlog.get_logger(__name__)

REPLICA_MERGE_CHUNK_SIZE = 500


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
        uow: IpDataPlaneUnitOfWorkPort,
        extractor_registry: RecordExtractorRegistry | None = None,
        tiered_storage: TieredStoragePort | None = None,
    ) -> None:
        self._uow = uow
        self._extractor_registry = (
            extractor_registry if extractor_registry is not None else RecordExtractorRegistry()
        )
        self._tiered_storage = tiered_storage

    @staticmethod
    def _unwrap_inlined_body(body: JsonValue) -> JsonValue:
        if isinstance(body, dict):
            if WRAPPED_SCALAR_KEY in body:
                return body[WRAPPED_SCALAR_KEY]
            if RESERVED_RAW_BYTES_KEY in body:
                clean_body = {k: v for k, v in body.items() if k != RESERVED_RAW_BYTES_KEY}
                escaped_key = f"_escaped_{RESERVED_RAW_BYTES_KEY}"
                if escaped_key in clean_body:
                    clean_body[RESERVED_RAW_BYTES_KEY] = clean_body.pop(escaped_key)
                return clean_body
        return body

    async def _retrieve_s3_payload(
        self, s3_key: str, size_bytes: int, sha256: str, inbound_record_id: str
    ) -> Result[JsonValue, IpError]:
        if self._tiered_storage is None:
            return Result.fail(
                PayloadNotFoundError(
                    s3_key=s3_key,
                    message="Tiered storage adapter is not configured to retrieve S3 payload.",
                )
            )
        storage_dto = TieredStorageResultDTO(
            is_inlined=False,
            raw_payload=None,
            s3_key=s3_key,
            payload_size_bytes=size_bytes,
            payload_sha256=sha256,
        )
        retrieved = await self._tiered_storage.retrieve(storage_dto)
        if retrieved.is_ok and retrieved.value is not None:
            try:
                parsed: JsonValue = json.loads(retrieved.value.decode("utf-8"))
                return Result.ok(parsed)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return Result.fail(
                    PayloadNotFoundError(
                        s3_key=s3_key,
                        message=f"Corrupt or non-JSON S3 payload for record '{inbound_record_id}': {e}",
                    )
                )
        return Result.fail(
            PayloadNotFoundError(
                s3_key=s3_key,
                message=f"Failed to retrieve S3 payload for record '{inbound_record_id}'.",
            )
        )

    async def _resolve_raw_payload(
        self, command: ReplicateRecordsCommand
    ) -> Result[JsonValue, IpError]:
        if command.raw_payload is not None:
            return Result.ok(command.raw_payload)
        inbound = await self._uow.inbound_records.get_by_id(
            record_id=command.inbound_record_id,
            tenant_id=command.tenant_id,
        )
        if inbound is None:
            return Result.fail(
                PayloadNotFoundError(
                    message=f"Inbound record '{command.inbound_record_id}' not found for tenant '{command.tenant_id}'."
                )
            )
        if inbound.request_body is not None:
            return Result.ok(self._unwrap_inlined_body(inbound.request_body))
        if inbound.request_s3_key is not None:
            return await self._retrieve_s3_payload(
                s3_key=inbound.request_s3_key,
                size_bytes=inbound.request_size_bytes,
                sha256=inbound.request_sha256,
                inbound_record_id=command.inbound_record_id,
            )
        return Result.fail(
            PayloadNotFoundError(
                message=f"No inline or S3 payload present for record '{command.inbound_record_id}'."
            )
        )

    async def execute(
        self, command: ReplicateRecordsCommand
    ) -> Result[ReplicationSummary, IpError]:
        stream_def = command.stream_definition or StreamDefinition(
            stream=command.stream,
            primary_key=(("id",),),
        )
        extractor = self._extractor_registry.get(stream_def.extractor_id)

        merge_results: list[MergeResult] = []
        rejections: list[ReplicaRejection] = []

        async with self._uow:
            # 1. Resolve raw payload inside opened Data Plane UoW
            payload_res = await self._resolve_raw_payload(command)
            if payload_res.is_err and payload_res.error is not None:
                return Result.fail(payload_res.error)
            raw_payload = payload_res.value

            # 2. Run pure extraction
            batch = extractor.extract(raw_payload, stream_def)

            # 3. Assemble merge candidates
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
                        cursor_value=(
                            str(rec.cursor_value) if rec.cursor_value is not None else None
                        ),
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

            # 4. Merge candidates in chunks of REPLICA_MERGE_CHUNK_SIZE (500)
            for idx in range(0, len(candidates), REPLICA_MERGE_CHUNK_SIZE):
                chunk = candidates[idx : idx + REPLICA_MERGE_CHUNK_SIZE]
                chunk_results = await self._uow.replica_records.merge_batch(chunk)
                merge_results.extend(chunk_results)

            # 5. Save rejections
            now = datetime.now(UTC)
            for rej in batch.rejections:
                rejections.append(
                    ReplicaRejection.create(
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
            await self._uow.commit()

        # 6. Tally summary counts
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
