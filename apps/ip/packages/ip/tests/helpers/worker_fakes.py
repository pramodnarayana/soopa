"""Shared pure in-memory test fakes for IP Engine worker route registry and job module unit tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence

from ip.engine.adapters.inbound.workers import (
    IpBackfillStreamNormalizationExecutorPort,
    IpFetchRecordExecutorPort,
    IpNormalizeReplicaExecutorPort,
    IpOutboundDeliveryExecutorPort,
    IpProcessInboundRangeExecutorPort,
    IpRunSyncExecutorPort,
    IpStitchCanonicalDispatcherPort,
    IpStitchWorkerTickExecutorPort,
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
    RunSyncResultDTO,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationResultDTO,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
)
from ip.engine.application.use_cases.normalization.process_inbound_range_use_case import (
    CanonicalChangeItemDTO,
    ProcessInboundRangeCommand,
    ProcessInboundRangeResultDTO,
)
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicationSummary,
)
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
    StitchWorkerTickResultDTO,
)
from ip.engine.domain.dispatch.enums import (
    FailureDisposition,
    HttpWriteOperation,
    OutboundDispatchStatus,
)
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.exceptions import (
    IpError,
    IpErrorCode,
    PayloadNotFoundError,
    Result,
    TenantShardNotFoundError,
)
from ip.engine.domain.intervals.enums import BatchManifestStatus
from ip.engine.domain.intervals.models import BatchManifest, BatchReconciliationSummary
from ip.engine.domain.normalization.enums import NormalizationOutcome
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.replication.enums import (
    CursorKind,
    MergeOutcome,
    SyncMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import (
    ReplicaMergePolicy,
    ReplicaRecord,
    ReplicaRejection,
)
from ip.engine.domain.replication.stream_definition import StreamDefinition
from ip.engine.ports.outbound.batch_manifest_repository_port import (
    BatchManifestRepositoryPort,
)
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from ip.engine.ports.outbound.pipeline_event_policy_port import ReplicationEventPolicyPort
from ip.engine.ports.outbound.quarantine_record_repository_port import (
    QuarantineRecordRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
    ReplicaRecordRepositoryPort,
)
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from orchestration.domain.exceptions import Result as WorkflowResult
from orchestration.domain.exceptions import WorkflowError
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import DomainEvent, EventEnvelope
from strace.ports import TraceRepositoryPort
from strace.ports.retention_repository_port import TraceRetentionRepositoryPort

from helpers.trace_fakes import (
    DummyEntityMapRepo,
    DummyLedgerRepo,
    DummyNormRejectionRepo,
    DummyPendingRefRepo,
    InMemoryQuarantineRecordRepo,
    InMemoryTraceRepo,
)


class FakeOutboxPublisher(OutboxPublisherPort):
    """In-memory OutboxPublisherPort recording published EventEnvelopes."""

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published.append(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        self.published.extend(events)
        return [e.id for e in events]


class FakeOutboxRepository(OutboxRepositoryPort, OutboxCleanupRepositoryPort):
    """In-memory OutboxRepositoryPort + OutboxCleanupRepositoryPort."""

    def __init__(self, initial_events: list[EventEnvelope] | None = None) -> None:
        self.pending: list[EventEnvelope] = list(initial_events or [])
        self.completed_batches: list[list[str]] = []
        self.failed_batches: list[tuple[list[str], str]] = []
        self.swept_leases: list[int] = []
        self.cleaned_retention_days: list[int] = []

    async def claim_next_events(
        self, worker_id: str, limit: int = 50, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        claimed = self.pending[:limit]
        self.pending = self.pending[limit:]
        return claimed

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        self.completed_batches.append([event_id])

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        self.completed_batches.append(list(event_ids))

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        self.failed_batches.append(([event_id], error_message))

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        self.failed_batches.append((list(event_ids), error_message))

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        self.swept_leases.append(lock_lease_ms)
        return 2

    async def cleanup_outbox(self, retention_days: int) -> int:
        self.cleaned_retention_days.append(retention_days)
        return 5


class FakeTraceRetentionRepository(TraceRetentionRepositoryPort):
    """In-memory TraceRetentionRepositoryPort."""

    def __init__(self) -> None:
        self.trace_retention_days: list[int] = []
        self.processed_retention_days: list[int] = []

    async def cleanup_trace_events(self, retention_days: int, concurrency_limit: int = 5) -> int:
        self.trace_retention_days.append(retention_days)
        return 7

    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> int:
        self.processed_retention_days.append(retention_days)
        return 4


class FakeTieredStorage(TieredStoragePort):
    """In-memory TieredStoragePort storing raw byte blobs by S3 key."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        key = f"s3://ip-test/{tenant_id}/{trace_id}"
        self.blobs[key] = payload_bytes
        return TieredStorageResultDTO(
            is_inlined=False,
            raw_payload=None,
            s3_key=key,
            payload_size_bytes=len(payload_bytes),
            payload_sha256="sha256_test",
        )

    async def retrieve(
        self,
        storage_ref: TieredStorageResultDTO,
    ) -> Result[bytes, PayloadNotFoundError]:
        if storage_ref.s3_key and storage_ref.s3_key in self.blobs:
            return Result.ok(self.blobs[storage_ref.s3_key])
        return Result.err(
            PayloadNotFoundError(
                message="Blob not found",
                details={"s3_key": storage_ref.s3_key or ""},
            )
        )


class FakeInboundRecordRepo(InboundRecordRepositoryPort):
    """In-memory InboundRecordRepositoryPort."""

    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def save_batch(self, records: Sequence[InboundRecord]) -> None:
        for record in records:
            self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str | None = None) -> InboundRecord | None:
        rec = self.records.get(record_id)
        if rec and (tenant_id is None or rec.tenant_id == tenant_id):
            return rec
        return None

    async def list_by_range(
        self,
        tenant_id: str,
        *,
        batch_id: str = "",
        range_start: str = "",
        range_end: str = "",
        record_ids: Sequence[str] = (),
    ) -> Sequence[InboundRecord]:
        if batch_id and range_start and range_end:
            matched = [
                r
                for r in self.records.values()
                if r.tenant_id == tenant_id
                and r.batch_id == batch_id
                and range_start <= r.id <= range_end
            ]
            return sorted(matched, key=lambda r: (r.batch_seq, r.id))
        if batch_id:
            matched = [
                r
                for r in self.records.values()
                if r.tenant_id == tenant_id and r.batch_id == batch_id
            ]
            return sorted(matched, key=lambda r: (r.batch_seq, r.id))
        target_ids = list(record_ids)
        if not target_ids and range_start:
            target_ids = (
                [range_start]
                if not range_end or range_end == range_start
                else [range_start, range_end]
            )
        return [
            self.records[rec_id]
            for rec_id in target_ids
            if rec_id in self.records and self.records[rec_id].tenant_id == tenant_id
        ]

    async def get_by_external_event_id(
        self,
        tenant_id: str,
        connection_id: str,
        external_event_id: str,
    ) -> InboundRecord | None:
        return None

    async def get_by_trace_id(
        self, trace_id: str, tenant_id: str, *, hydrate_payloads: bool = False
    ) -> Sequence[InboundRecord]:
        return [
            r for r in self.records.values() if r.tenant_id == tenant_id and r.trace_id == trace_id
        ]

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        stream_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        _ = hydrate_payloads
        res = [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and (connection_id is None or r.connection_id == connection_id)
            and (stream_name is None or r.stream_name == stream_name)
        ]
        return res[offset : offset + limit]


class FakeReplicaRecordRepo(ReplicaRecordRepositoryPort):
    """In-memory ReplicaRecordRepositoryPort."""

    def __init__(self) -> None:
        self.records: dict[str, ReplicaRecord] = {}
        self.merged_candidates: list[ReplicaMergeCandidate] = []
        self.events: list[DomainEvent] = []

    async def save(self, record: ReplicaRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(
        self,
        tenant_id: str,
        record_id: str,
    ) -> ReplicaRecord | None:
        rec = self.records.get(record_id)
        if rec and rec.tenant_id == tenant_id:
            return rec
        return None

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        for rec in self.records.values():
            if (
                rec.tenant_id == tenant_id
                and rec.connection_id == connection_id
                and rec.stream == stream
                and rec.record_key == record_key
            ):
                return rec
        return None

    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
        *,
        event_policy: ReplicationEventPolicyPort | None = None,
    ) -> list[MergeResult]:
        self.merged_candidates.extend(candidates)
        results: list[MergeResult] = []
        changed: list[ReplicaRecord] = []
        for cand in candidates:
            existing = await self.get_by_key(
                cand.tenant_id,
                cand.connection_id,
                cand.stream,
                cand.record_key,
            )
            cursor_kind = (
                CursorKind(cand.cursor_kind)
                if cand.cursor_kind is not None
                and cand.cursor_kind in CursorKind.__members__.values()
                else CursorKind.STRING
            )
            outcome = ReplicaMergePolicy.evaluate(
                existing=existing,
                incoming_data_hash=cand.data_hash,
                incoming_cursor=cand.cursor_value,
                cursor_kind=cursor_kind,
                is_deleted=cand.is_deleted,
            )
            if outcome == MergeOutcome.INSERT:
                rec = ReplicaRecord.create(
                    tenant_id=cand.tenant_id,
                    connection_id=cand.connection_id,
                    stream=cand.stream,
                    record_key=cand.record_key,
                    primary_key_values=cand.primary_key_values,
                    cursor_value=cand.cursor_value,
                    cursor_kind=cand.cursor_kind,
                    data=cand.data,
                    generation_id=cand.generation_id,
                    source_inbound_record_id=cand.source_inbound_record_id,
                    trace_id=cand.trace_id,
                    correlation_id=cand.correlation_id,
                )
                self.records[rec.id] = rec
                changed.append(rec)
                results.append(
                    MergeResult(
                        record_id=rec.id,
                        stream=cand.stream,
                        record_key=cand.record_key,
                        outcome=MergeOutcome.INSERT,
                        version=rec.version,
                        data_hash=rec.data_hash,
                        replica=rec,
                    )
                )
            elif outcome == MergeOutcome.UPDATE and existing is not None:
                existing.update_snapshot(
                    new_data=cand.data,
                    trace_id=cand.trace_id,
                    correlation_id=cand.correlation_id,
                    cursor_value=cand.cursor_value,
                    generation_id=cand.generation_id,
                    source_inbound_record_id=cand.source_inbound_record_id,
                )
                changed.append(existing)
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=cand.stream,
                        record_key=cand.record_key,
                        outcome=MergeOutcome.UPDATE,
                        version=existing.version,
                        data_hash=existing.data_hash,
                        replica=existing,
                    )
                )
            elif outcome == MergeOutcome.TOMBSTONE:
                if existing is None:
                    existing = ReplicaRecord.create_tombstone(
                        tenant_id=cand.tenant_id,
                        connection_id=cand.connection_id,
                        stream=cand.stream,
                        record_key=cand.record_key,
                        primary_key_values=cand.primary_key_values,
                        cursor_value=str(cand.cursor_value)
                        if cand.cursor_value is not None
                        else None,
                        cursor_kind=cand.cursor_kind,
                        data=cand.data,
                        generation_id=cand.generation_id,
                        source_inbound_record_id=cand.source_inbound_record_id,
                        trace_id=cand.trace_id,
                        correlation_id=cand.correlation_id,
                    )
                    self.records[existing.id] = existing
                else:
                    existing.tombstone(
                        trace_id=cand.trace_id,
                        correlation_id=cand.correlation_id,
                        generation_id=cand.generation_id,
                        source_inbound_record_id=cand.source_inbound_record_id,
                    )
                changed.append(existing)
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=cand.stream,
                        record_key=cand.record_key,
                        outcome=MergeOutcome.TOMBSTONE,
                        version=existing.version,
                        data_hash=cand.data_hash,
                        replica=existing,
                    )
                )
            else:
                if existing is not None:
                    if outcome == MergeOutcome.NOOP:
                        existing.last_seen_generation = cand.generation_id
                    results.append(
                        MergeResult(
                            record_id=existing.id,
                            stream=cand.stream,
                            record_key=cand.record_key,
                            outcome=outcome,
                            version=existing.version,
                            data_hash=existing.data_hash,
                            replica=existing,
                        )
                    )

        to_emit = (
            event_policy.select_outbox_replicas(changed)
            if event_policy is not None
            else tuple(changed)
        )
        for agg in to_emit:
            self.events.extend(agg.domain_events)
            agg.clear_domain_events()
        return results

    async def tombstone_unseen_generations(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        current_generation: int,
        limit: int = 500,
        trace_id: str = "",
    ) -> int:
        return 0

    async def list_by_stream_chunk(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        after_id: str | None = None,
        limit: int = 100,
    ) -> list[ReplicaRecord]:
        return []

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        stream: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ReplicaRecord]:
        res = [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and (connection_id is None or r.connection_id == connection_id)
            and (stream is None or r.stream == stream)
        ]
        return res[offset : offset + limit]


class FakeReplicaRejectionRepo(ReplicaRejectionRepositoryPort):
    """In-memory ReplicaRejectionRepositoryPort."""

    def __init__(self) -> None:
        self.rejections: list[ReplicaRejection] = []

    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        self.rejections.extend(rejections)


class FakeOutboundRecordRepo(OutboundRecordRepositoryPort):
    """In-memory OutboundRecordRepositoryPort."""

    def __init__(self) -> None:
        self.records: dict[str, OutboundRecord] = {}

    async def save(self, record: OutboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(
        self, record_id: str, tenant_id: str | None = None
    ) -> OutboundRecord | None:
        rec = self.records.get(record_id)
        if rec and (tenant_id is None or rec.tenant_id == tenant_id):
            return rec
        return None

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None:
        for rec in self.records.values():
            if (
                rec.tenant_id == tenant_id
                and rec.connection_id == connection_id
                and rec.idempotency_key == idempotency_key
            ):
                return rec
        return None

    async def get_by_trace_id(
        self, trace_id: str, tenant_id: str, *, hydrate_payloads: bool = False
    ) -> Sequence[OutboundRecord]:
        return [
            r for r in self.records.values() if r.tenant_id == tenant_id and r.trace_id == trace_id
        ]


class FakeNormalizedRecordRepo(NormalizedRecordRepositoryPort):
    """In-memory NormalizedRecordRepositoryPort."""

    def __init__(self) -> None:
        self.records: dict[str, NormalizedRecord] = {}

    async def save(self, record: NormalizedRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        rec = self.records.get(record_id)
        if rec and rec.tenant_id == tenant_id:
            return rec
        return None

    async def list_by_source(
        self,
        tenant_id: str,
        canonical_type: str,
        source_id: str,
        connection_id: str | None = None,
    ) -> Sequence[NormalizedRecord]:
        return [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and r.canonical_type == canonical_type
            and r.source_id == source_id
            and (connection_id is None or r.connection_id == connection_id)
        ]


class InMemoryBatchManifestRepo(BatchManifestRepositoryPort):
    """In-memory BatchManifestRepositoryPort for testing interval macro-batch flows."""

    def __init__(self, manifests: Sequence[BatchManifest] | None = None) -> None:
        self.manifests: dict[str, BatchManifest] = {m.id: m for m in manifests} if manifests else {}

    async def save(self, manifest: BatchManifest) -> None:
        self.manifests[manifest.id] = manifest

    async def get_by_id(self, batch_id: str, tenant_id: str) -> BatchManifest | None:
        m = self.manifests.get(batch_id)
        if m is not None and m.tenant_id == tenant_id:
            return m
        return None

    async def get_by_sha256(
        self, tenant_id: str, connection_id: str, payload_sha256: str
    ) -> BatchManifest | None:
        for m in self.manifests.values():
            if (
                m.tenant_id == tenant_id
                and m.connection_id == connection_id
                and m.payload_sha256 == payload_sha256
            ):
                return m
        return None

    async def list_by_connection(
        self, tenant_id: str, *, connection_id: str | None = None, limit: int = 50
    ) -> Sequence[BatchManifest]:
        res = [
            m
            for m in self.manifests.values()
            if m.tenant_id == tenant_id
            and (connection_id is None or m.connection_id == connection_id)
        ]
        res.sort(key=lambda m: m.created_at, reverse=True)
        return res[:limit]

    async def get_reconciliation_summary(
        self, tenant_id: str, *, connection_id: str | None = None
    ) -> BatchReconciliationSummary:
        matching = [
            m
            for m in self.manifests.values()
            if m.tenant_id == tenant_id
            and (connection_id is None or m.connection_id == connection_id)
        ]
        total_batches = len(matching)
        completed_batches = sum(1 for m in matching if m.status is BatchManifestStatus.COMPLETED)
        in_flight_batches = sum(
            1
            for m in matching
            if m.status in (BatchManifestStatus.INGESTED, BatchManifestStatus.PROCESSING)
        )
        failed_batches = sum(
            1
            for m in matching
            if m.status in (BatchManifestStatus.FAILED, BatchManifestStatus.QUARANTINED)
        )
        raw_total = sum(m.raw_ingested_count for m in matching)
        valid_total = sum(m.valid_canonical_count for m in matching)
        dups_total = sum(m.duplicates_dropped_count for m in matching)
        quar_total = sum(m.quarantined_held_count for m in matching)
        in_flight_readings = sum(
            m.raw_ingested_count
            for m in matching
            if m.status in (BatchManifestStatus.INGESTED, BatchManifestStatus.PROCESSING)
        )
        accounted_plus_inflight = dups_total + valid_total + quar_total + in_flight_readings
        is_balanced = failed_batches == 0 and raw_total == accounted_plus_inflight

        return BatchReconciliationSummary(
            tenant_id=tenant_id,
            connection_id=connection_id,
            total_batches=total_batches,
            completed_batches=completed_batches,
            in_flight_batches=in_flight_batches,
            failed_batches=failed_batches,
            raw_ingested_total=raw_total,
            duplicates_dropped_total=dups_total,
            valid_canonical_total=valid_total,
            quarantined_held_total=quar_total,
            in_flight_readings_total=in_flight_readings,
            is_zero_loss_balanced=is_balanced,
        )


class FakeDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
    """In-memory IpDataPlaneUnitOfWorkPort with idempotency tracking and commit/rollback."""

    def __init__(
        self,
        *,
        inbound_records: FakeInboundRecordRepo | None = None,
        replica_records: FakeReplicaRecordRepo | None = None,
        replica_rejections: FakeReplicaRejectionRepo | None = None,
        normalized_records: FakeNormalizedRecordRepo | None = None,
        outbound_records: FakeOutboundRecordRepo | None = None,
        batch_manifests: InMemoryBatchManifestRepo | None = None,
    ) -> None:
        self.inbound_records = inbound_records or FakeInboundRecordRepo()
        self.replica_records = replica_records or FakeReplicaRecordRepo()
        self.replica_rejections = replica_rejections or FakeReplicaRejectionRepo()
        self.normalized_records = normalized_records or FakeNormalizedRecordRepo()
        self.outbound_records = outbound_records or FakeOutboundRecordRepo()
        self.quarantine_records: QuarantineRecordRepositoryPort = InMemoryQuarantineRecordRepo()
        self.traces: TraceRepositoryPort = InMemoryTraceRepo()
        self.entity_maps: GlobalEntityMapRepositoryPort = DummyEntityMapRepo()
        self.normalization_ledger: NormalizationLedgerRepositoryPort = DummyLedgerRepo()
        self.normalization_rejections: NormalizationRejectionRepositoryPort = (
            DummyNormRejectionRepo()
        )
        self.pending_references: PendingReferenceRepositoryPort = DummyPendingRefRepo()
        self.batch_manifests = batch_manifests or InMemoryBatchManifestRepo()
        self.committed_idempotency_keys: set[tuple[str, str]] = set()
        self._staged_idempotency_keys: set[tuple[str, str]] = set()
        self.commit_count = 0
        self.rollback_count = 0
        self.release_count = 0

    async def __aenter__(self) -> FakeDataPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        pair = (tenant_id, idempotency_key)
        if pair in self.committed_idempotency_keys or pair in self._staged_idempotency_keys:
            return False
        self._staged_idempotency_keys.add(pair)
        return True

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        pair = (tenant_id, idempotency_key)
        self.committed_idempotency_keys.discard(pair)
        self._staged_idempotency_keys.discard(pair)
        self.release_count += 1

    async def commit(self) -> None:
        self.commit_count += 1
        self.committed_idempotency_keys.update(self._staged_idempotency_keys)
        self._staged_idempotency_keys.clear()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self._staged_idempotency_keys.clear()


class FakeDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    """In-memory IpDataPlaneUnitOfWorkProviderPort."""

    def __init__(
        self,
        uow: FakeDataPlaneUoW,
        *,
        missing_tenant_ids: set[str] | None = None,
    ) -> None:
        self.uow = uow
        self.missing_tenant_ids = missing_tenant_ids or set()

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        if tenant_id in self.missing_tenant_ids:
            return Result.err(
                TenantShardNotFoundError(
                    message=f"Shard not found for {tenant_id}",
                    details={"tenant_id": tenant_id},
                )
            )
        return Result.ok(("ip_shard_1", "postgresql+asyncpg://localhost:5434/ip_shard"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        yield self.uow


class FakeNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    """In-memory IpNormalizeReplicaExecutorPort tracking concurrency."""

    def __init__(
        self,
        *,
        fail_ids: set[str] | None = None,
        delay_seconds: float = 0.01,
    ) -> None:
        self.executed_ids: list[str] = []
        self.fail_ids = fail_ids or set()
        self.delay_seconds = delay_seconds
        self.current_in_flight = 0
        self.max_observed_in_flight = 0

    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        self.current_in_flight += 1
        if self.current_in_flight > self.max_observed_in_flight:
            self.max_observed_in_flight = self.current_in_flight
        try:
            await asyncio.sleep(self.delay_seconds)
            self.executed_ids.append(command.replica_record_id)
            if command.replica_record_id in self.fail_ids:
                return Result.err(
                    IpError(
                        code=IpErrorCode.EXTERNAL_API_ERROR,
                        message="Transient failure",
                        disposition=FailureDisposition.RETRY,
                    )
                )
            return Result.ok(
                NormalizeReplicaRecordResultDTO(
                    outcome=NormalizationOutcome.NORMALIZED,
                    canonical_refs_produced=(
                        ("canonical.record_alpha.v1", command.replica_record_id),
                    ),
                )
            )
        finally:
            self.current_in_flight -= 1


class FakeBackfillExecutor(IpBackfillStreamNormalizationExecutorPort):
    """In-memory IpBackfillStreamNormalizationExecutorPort."""

    def __init__(self) -> None:
        self.commands: list[BackfillStreamNormalizationCommand] = []

    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        self.commands.append(command)
        return Result.ok(
            BackfillStreamNormalizationResultDTO(
                processed_count=3,
                normalized_count=3,
                rejected_count=0,
                tombstoned_count=0,
                skipped_count=0,
                chunks_processed=1,
            )
        )


class FakeStitchDispatcher(IpStitchCanonicalDispatcherPort):
    """In-memory IpStitchCanonicalDispatcherPort."""

    def __init__(self, *, started_run_ids: tuple[str, ...] = ("wf_run_01",)) -> None:
        self.commands: list[DispatchCanonicalEventToStitchesCommand] = []
        self.started_run_ids = started_run_ids

    async def execute(
        self, command: DispatchCanonicalEventToStitchesCommand
    ) -> WorkflowResult[DispatchCanonicalEventResultDTO, WorkflowError]:
        self.commands.append(command)
        return WorkflowResult.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=self.started_run_ids,
                deduplicated_run_ids=(),
                signalled_step_ids=(),
            )
        )


class FakeStitchTickExecutor(IpStitchWorkerTickExecutorPort):
    """In-memory IpStitchWorkerTickExecutorPort."""

    def __init__(self) -> None:
        self.commands: list[ExecuteStitchWorkerTickCommand] = []

    async def execute(
        self, command: ExecuteStitchWorkerTickCommand
    ) -> WorkflowResult[StitchWorkerTickResultDTO, WorkflowError]:
        self.commands.append(command)
        completed = ("step_01",) if len(self.commands) == 1 else ()
        return WorkflowResult.ok(
            StitchWorkerTickResultDTO(
                completed_step_ids=completed,
                failed_or_retried_step_ids=(),
                parked_step_ids=(),
                woken_timer_step_ids=(),
            )
        )


class FakeProcessInboundRangeExecutor(IpProcessInboundRangeExecutorPort):
    """In-memory IpProcessInboundRangeExecutorPort returning canonical changes for fused L2->L3."""

    def __init__(
        self,
        *,
        canonical_changes: tuple[CanonicalChangeItemDTO, ...] = (),
    ) -> None:
        self.commands: list[ProcessInboundRangeCommand] = []
        self.canonical_changes = canonical_changes

    async def execute(
        self, command: ProcessInboundRangeCommand
    ) -> Result[ProcessInboundRangeResultDTO, IpError]:
        self.commands.append(command)
        return Result.ok(
            ProcessInboundRangeResultDTO(
                replication_summary=ReplicationSummary(
                    inserted_count=command.count,
                    updated_count=0,
                    noop_count=0,
                    stale_count=0,
                    tombstone_count=0,
                    rejected_count=0,
                ),
                canonical_changes=self.canonical_changes,
                inbound_records_processed=command.count,
            )
        )


class FakeOutboundDeliveryExecutor(IpOutboundDeliveryExecutorPort):
    """In-memory IpOutboundDeliveryExecutorPort tracking concurrency."""

    def __init__(
        self,
        *,
        status_by_key: dict[str, OutboundDispatchStatus] | None = None,
        retry_after_by_key: dict[str, int] | None = None,
        quarantined_keys: set[str] | None = None,
        delay_seconds: float = 0.01,
    ) -> None:
        self.commands: list[DeliverOutboundRecordCommand] = []
        self.status_by_key = status_by_key or {}
        self.retry_after_by_key = retry_after_by_key or {}
        self.quarantined_keys = quarantined_keys or set()
        self.delay_seconds = delay_seconds
        self.current_in_flight = 0
        self.max_observed_in_flight = 0

    async def execute(
        self, command: DeliverOutboundRecordCommand
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        self.current_in_flight += 1
        if self.current_in_flight > self.max_observed_in_flight:
            self.max_observed_in_flight = self.current_in_flight
        try:
            await asyncio.sleep(self.delay_seconds)
            self.commands.append(command)
            idem = command.idempotency_key or "default"
            status = self.status_by_key.get(idem, OutboundDispatchStatus.DELIVERED)
            return Result.ok(
                DeliverOutboundRecordResponse(
                    outbound_record_id=idem,
                    status=status,
                    trace_id=command.trace_id or "tr_out",
                    idempotency_key=idem,
                    record_id=command.record_id or idem,
                    destination_id=f"dest_{idem}",
                    response_status_code=200 if status is OutboundDispatchStatus.DELIVERED else 503,
                    duration_ms=10,
                    was_quarantined=idem in self.quarantined_keys,
                    retry_after_seconds=self.retry_after_by_key.get(idem),
                    error_message=None
                    if status is OutboundDispatchStatus.DELIVERED
                    else "Downstream failure",
                )
            )
        finally:
            self.current_in_flight -= 1


class FakeFetchRecordExecutor(IpFetchRecordExecutorPort):
    """In-memory IpFetchRecordExecutorPort."""

    def __init__(self, *, status: str = "FETCHED") -> None:
        self.commands: list[FetchRecordCommand] = []
        self.status = status

    async def execute(self, command: FetchRecordCommand) -> FetchRecordResultDTO:
        self.commands.append(command)
        return FetchRecordResultDTO(
            status=self.status,
            trace_id=command.trace_id or "tr_fetch",
            record_id=command.record_id,
            inbound_record_id=f"inb_{command.record_id}",
        )


class FakeRunSyncExecutor(IpRunSyncExecutorPort):
    """In-memory IpRunSyncExecutorPort."""

    def __init__(
        self,
        *,
        status: str = SyncRunStatus.SUCCEEDED.value,
        error_code: str | None = None,
    ) -> None:
        self.commands: list[RunSyncCommand] = []
        self.status = status
        self.error_code = error_code

    async def execute(self, command: RunSyncCommand) -> RunSyncResultDTO:
        self.commands.append(command)
        return RunSyncResultDTO(
            run_id="run_01",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            kind=SyncRunKind.INCREMENTAL.value,
            status=self.status,
            pages_synced=2,
            records_synced=50,
            bytes_synced=4096,
            error_code=self.error_code,
            error_message="Sync error" if self.error_code else None,
        )


def make_stream_definition() -> StreamDefinition:
    return StreamDefinition(
        stream="records_alpha",
        primary_key=(("record_id",),),
        cursor_field=("updated_at",),
        cursor_kind=CursorKind.STRING,
        sync_mode=SyncMode.INCREMENTAL,
    )


def make_outbound_record(
    record_id: str,
    *,
    status: OutboundDispatchStatus = OutboundDispatchStatus.PENDING,
    is_inlined: bool = True,
    request_body: JsonDict | None = None,
    request_s3_key: str | None = None,
    causation_depth: int = 0,
) -> OutboundRecord:
    body: JsonDict = request_body if request_body is not None else {"invoice_id": record_id}
    raw_bytes = json.dumps(body).encode("utf-8")
    rec = OutboundRecord.create_pending(
        tenant_id="t_01",
        connection_id="conn_01",
        app_id="erp_app",
        stream_name="erp_invoices",
        target_url="https://api.example.com/invoices",
        http_method="POST",
        payload_bytes=raw_bytes,
        is_inlined=is_inlined,
        trace_id="tr_out_01",
        operation=HttpWriteOperation.UPSERT.value,
        idempotency_key=f"idem_{record_id}",
        external_record_id=record_id,
        request_body=body if is_inlined else None,
        request_s3_key=request_s3_key,
        causation_depth=causation_depth,
        status=status,
    )
    rec.id = record_id
    return rec
