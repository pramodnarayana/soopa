"""Unit tests for IP Engine inbound worker adapters, route registries, DTOs, and disposition handlers.

Zero mocks (`unittest.mock`, `MagicMock`, `AsyncMock`, `patch`, `monkeypatch` are strictly forbidden).
All dependencies use strongly-typed in-memory fakes implementing the exact Engine ports.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import cast

import pytest
from ip.engine.adapters.inbound.workers import (
    IpBackfillStreamNormalizationExecutorPort,
    IpCanonicalRecordChunkPayloadDTO,
    IpCpJobsWorkerModule,
    IpDeliveryRouteRegistry,
    IpDeliveryWorkerModule,
    IpDpJobsWorkerModule,
    IpFetchRecordChunkPayloadDTO,
    IpFetchRecordExecutorPort,
    IpGenerationCompletedPayloadDTO,
    IpInboundRecordChunkPayloadDTO,
    IpMultiShardStitchTickLoop,
    IpNormalizedRecordChunkPayloadDTO,
    IpNormalizeReplicaExecutorPort,
    IpOrchestratorRouteRegistry,
    IpOrchestratorWorkerModule,
    IpOutboundDeliveryExecutorPort,
    IpOutboundRecordChunkPayloadDTO,
    IpReplicaRecordChunkPayloadDTO,
    IpRunSyncExecutorPort,
    IpStitchCanonicalDispatcherPort,
    IpStitchWorkerTickExecutorPort,
    IpStreamBackfillPayloadDTO,
    IpSyncRunRequestedPayloadDTO,
    IpWorkerResultDispositionHandler,
)
from ip.engine.adapters.outbound.pubsub.publisher_factory import (
    build_ip_cp_outbox_router,
    build_ip_dp_outbox_router,
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
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
    StitchWorkerTickResultDTO,
)
from ip.engine.domain.enums import (
    CursorKind,
    FailureDisposition,
    HttpWriteOperation,
    IngestionMode,
    IpEventType,
    IpJobName,
    MergeOutcome,
    NormalizationOutcome,
    OutboundDispatchStatus,
    SyncMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.exceptions import (
    IpError,
    IpErrorCode,
    PayloadNotFoundError,
    Result,
    TenantShardNotFoundError,
)
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import (
    InboundRecordRepositoryPort,
)
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import (
    OutboundRecordRepositoryPort,
)
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
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
from ip.engine.settings import IpEngineSettings
from orchestration.domain.exceptions import Result as WorkflowResult
from orchestration.domain.exceptions import WorkflowError
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from pubsub.enums import ConsumerAction
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import DomainEvent, EventEnvelope, EventProcessingLane
from strace.application.clean_trace_retention_use_case import (
    CleanTraceRetentionUseCase,
)
from strace.ports import TraceRepositoryPort
from strace.ports.retention_repository_port import TraceRetentionRepositoryPort
from unified_worker.registry import get_worker_instance

# ==============================================================================
# Pure In-Memory Test Fakes (Zero Mocks)
# ==============================================================================


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

    async def get_by_id(self, record_id: str, tenant_id: str | None = None) -> InboundRecord | None:
        rec = self.records.get(record_id)
        if rec and (tenant_id is None or rec.tenant_id == tenant_id):
            return rec
        return None

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
    ) -> list[MergeResult]:
        self.merged_candidates.extend(candidates)
        results: list[MergeResult] = []
        for cand in candidates:
            rec_id = f"ip_rep_{cand.record_key}"
            results.append(
                MergeResult(
                    record_id=rec_id,
                    stream=cand.stream,
                    record_key=cand.record_key,
                    outcome=MergeOutcome.INSERT,
                    version=1,
                    data_hash=cand.data_hash,
                )
            )
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
    ) -> Sequence[NormalizedRecord]:
        return [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and r.canonical_type == canonical_type
            and r.source_id == source_id
        ]


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
    ) -> None:
        self.inbound_records = inbound_records or FakeInboundRecordRepo()
        self.replica_records = replica_records or FakeReplicaRecordRepo()
        self.replica_rejections = replica_rejections or FakeReplicaRejectionRepo()
        self.normalized_records = normalized_records or FakeNormalizedRecordRepo()
        self.outbound_records = outbound_records or FakeOutboundRecordRepo()
        self.traces = cast(TraceRepositoryPort, object())
        self.entity_maps = cast(GlobalEntityMapRepositoryPort, object())
        self.normalization_ledger = cast(NormalizationLedgerRepositoryPort, object())
        self.normalization_rejections = cast(NormalizationRejectionRepositoryPort, object())
        self.pending_references = cast(PendingReferenceRepositoryPort, object())
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
                        ("energy.meter_reading.v1", command.replica_record_id),
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


class FakeOutboundDeliveryExecutor(IpOutboundDeliveryExecutorPort):
    """In-memory IpOutboundDeliveryExecutorPort tracking concurrency."""

    def __init__(
        self,
        *,
        status_by_key: dict[str, OutboundDispatchStatus] | None = None,
        delay_seconds: float = 0.01,
    ) -> None:
        self.commands: list[DeliverOutboundRecordCommand] = []
        self.status_by_key = status_by_key or {}
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


# ==============================================================================
# 1. Payload DTO Tests
# ==============================================================================


def test_payload_dtos_parse_chunk_pointers_and_single_fallbacks() -> None:
    """Verify all 9 Ip*PayloadDTO classes parse both chunk-pointer tuples and single-ID fallbacks."""
    inbound_env = EventEnvelope(
        id="evt_1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k_1",
        trace_id="tr_1",
        payload={
            "connection_id": "conn_1",
            "stream_name": "meter_reads",
            "record_ids": ["inb_1", "inb_2"],
            "generation_id": 2,
        },
    )
    inbound_res = IpInboundRecordChunkPayloadDTO.from_envelope(inbound_env)
    assert inbound_res.is_ok
    assert inbound_res.unwrap().record_ids == ("inb_1", "inb_2")
    assert inbound_res.unwrap().generation_id == 2

    # Single record_id fallback
    inbound_single = IpInboundRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_2",
            source="ip.data_plane",
            event_type=IpEventType.INBOUND_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_2",
            payload={
                "connection_id": "conn_1",
                "stream": "meter_reads",
                "record_id": "inb_single",
            },
        )
    )
    assert inbound_single.is_ok
    assert inbound_single.unwrap().record_ids == ("inb_single",)

    # Validation failure when record_ids is missing
    inbound_invalid = IpInboundRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_bad",
            source="ip.data_plane",
            event_type=IpEventType.INBOUND_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_bad",
            payload={"connection_id": "conn_1", "stream_name": "meter_reads"},
        )
    )
    assert inbound_invalid.is_err
    assert inbound_invalid.unwrap_err().code == IpErrorCode.VALIDATION_FAILED

    replica_res = IpReplicaRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_rep",
            source="ip.data_plane",
            event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
            tenant_id="t_01",
            idempotency_key="k_rep",
            payload={
                "connection_id": "conn_1",
                "stream": "meter_reads",
                "record_ids": ["rep_1", "rep_2", "rep_3"],
                "version": 4,
            },
        )
    )
    assert replica_res.is_ok
    assert replica_res.unwrap().record_ids == ("rep_1", "rep_2", "rep_3")
    assert replica_res.unwrap().version == 4

    norm_res = IpNormalizedRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_norm",
            source="ip.data_plane",
            event_type=IpEventType.NORMALIZED_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_norm",
            payload={
                "connection_id": "conn_1",
                "canonical_type": "energy.meter_reading.v1",
                "source_id": "MTR-1",
                "record_id": "norm_1",
            },
        )
    )
    assert norm_res.is_ok
    assert norm_res.unwrap().record_ids == ("norm_1",)

    canon_res = IpCanonicalRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_canon",
            source="ip.data_plane",
            event_type=IpEventType.CANONICAL_RECORD_CHANGED.value,
            tenant_id="t_01",
            idempotency_key="k_canon",
            payload={
                "connection_id": "conn_1",
                "canonical_type": "energy.meter_reading.v1",
                "source_id": "MTR-100",
            },
        )
    )
    assert canon_res.is_ok
    assert canon_res.unwrap().record_ids == ("MTR-100",)

    outbound_res = IpOutboundRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_out",
            source="ip.data_plane",
            event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_out",
            payload={
                "connection_id": "conn_1",
                "stream_name": "erp_invoices",
                "record_ids": ["out_1", "out_2"],
            },
        )
    )
    assert outbound_res.is_ok
    assert outbound_res.unwrap().record_ids == ("out_1", "out_2")

    fetch_res = IpFetchRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_fetch",
            source="ip.data_plane",
            event_type=IpEventType.FETCH_RECORD_REQUESTED.value,
            tenant_id="t_01",
            idempotency_key="k_fetch",
            payload={
                "connection_id": "conn_1",
                "stream": "orders",
                "record_id": "ORD-1",
                "notice_inbound_record_id": "inb_notice_1",
            },
        )
    )
    assert fetch_res.is_ok
    assert fetch_res.unwrap().record_ids == ("ORD-1",)

    gen_res = IpGenerationCompletedPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_gen",
            source="ip.data_plane",
            event_type=IpEventType.GENERATION_COMPLETED.value,
            tenant_id="t_01",
            idempotency_key="k_gen",
            payload={"connection_id": "conn_1", "stream": "meters", "generation_id": 7},
        )
    )
    assert gen_res.is_ok
    assert gen_res.unwrap().generation_id == 7

    backfill_res = IpStreamBackfillPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_bf",
            source="ip.control_plane",
            event_type=IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
            tenant_id="t_01",
            idempotency_key="k_bf",
            payload={"connection_id": "conn_1", "stream": "meters", "transformation_id": "map_1"},
        )
    )
    assert backfill_res.is_ok
    assert backfill_res.unwrap().transformation_id == "map_1"

    sync_res = IpSyncRunRequestedPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_sync",
            source="ip.control_plane",
            event_type=IpEventType.SYNC_RUN_REQUESTED.value,
            tenant_id="t_01",
            idempotency_key="k_sync",
            payload={
                "connection_id": "conn_1",
                "stream": "meters",
                "kind": SyncRunKind.INCREMENTAL.value,
            },
        )
    )
    assert sync_res.is_ok
    assert sync_res.unwrap().forced_kind is SyncRunKind.INCREMENTAL


# ==============================================================================
# 2. Disposition Handler Tests
# ==============================================================================


def test_disposition_handler_maps_all_failure_dispositions_and_batches() -> None:
    """Verify IpWorkerResultDispositionHandler maps Result[T, IpError] to ConsumerAction."""
    env = EventEnvelope(
        id="evt_disp",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k_disp",
        payload={},
    )

    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.ok("ok"))
        == ConsumerAction.ACK
    )

    retry_err = IpError(
        code=IpErrorCode.EXTERNAL_API_ERROR,
        message="Rate limited",
        disposition=FailureDisposition.RETRY,
    )
    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.err(retry_err))
        == ConsumerAction.NACK
    )

    fail_err = IpError(
        code=IpErrorCode.VALIDATION_FAILED,
        message="Poison pill",
        disposition=FailureDisposition.FAIL,
    )
    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.err(fail_err))
        == ConsumerAction.DLQ
    )

    ignore_err = IpError(
        code=IpErrorCode.VALIDATION_FAILED,
        message="Duplicate",
        disposition=FailureDisposition.IGNORE,
    )
    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.err(ignore_err))
        == ConsumerAction.ACK
    )

    # Chunk evaluation precedence: NACK > DLQ > ACK
    assert (
        IpWorkerResultDispositionHandler.to_chunk_consumer_action(env, [Result.ok(1), Result.ok(2)])
        == ConsumerAction.ACK
    )
    assert (
        IpWorkerResultDispositionHandler.to_chunk_consumer_action(
            env, [Result.ok(1), Result.err(fail_err)]
        )
        == ConsumerAction.DLQ
    )
    assert (
        IpWorkerResultDispositionHandler.to_chunk_consumer_action(
            env, [Result.ok(1), Result.err(fail_err), Result.err(retry_err)]
        )
        == ConsumerAction.NACK
    )


# ==============================================================================
# 3. IpOrchestratorRouteRegistry Tests (Realtime N=1 & Bulk N=K)
# ==============================================================================


def _make_stream_definition() -> StreamDefinition:
    return StreamDefinition(
        stream="meter_reads",
        primary_key=(("meter_id",),),
        cursor_field=("read_at",),
        cursor_kind=CursorKind.STRING,
        sync_mode=SyncMode.INCREMENTAL,
    )


@pytest.mark.asyncio
async def test_orchestrator_route_registry_inbound_realtime_and_bulk_and_idempotency() -> None:
    """Verify IpOrchestratorRouteRegistry handles L1->L2 chunk pointers and idempotency."""
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow)
    storage = FakeTieredStorage()

    # Seed two inbound records in L1
    for idx in (1, 2):
        body: JsonDict = {
            "meter_id": f"MTR-{idx}",
            "kwh": 10.5 * idx,
            "read_at": "2026-10-27T00:00:00Z",
        }
        raw_bytes = json.dumps(body).encode("utf-8")
        rec = InboundRecord.create(
            tenant_id="t_01",
            connection_id="conn_01",
            app_id="itron",
            stream_name="meter_reads",
            payload_bytes=raw_bytes,
            is_inlined=True,
            request_body=body,
            trace_id="tr_01",
            ingestion_mode=IngestionMode.PUSH_FULL,
        )
        rec.id = f"inb_{idx}"
        uow.inbound_records.records[f"inb_{idx}"] = rec

    normalize_exec = FakeNormalizeExecutor()
    backfill_exec = FakeBackfillExecutor()
    stitch_disp = FakeStitchDispatcher()
    stitch_tick = FakeStitchTickExecutor()

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=uow_provider,
        normalize_use_case=normalize_exec,
        backfill_use_case=backfill_exec,
        tiered_storage=storage,
        stitch_dispatcher=stitch_disp,
        stitch_worker_tick=stitch_tick,
        stream_definition_resolver=lambda t, c, s: _make_stream_definition(),
        max_chunk_concurrency=4,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    # 1. Dispatch Bulk N=2 inbound_record.created chunk envelope
    envelope = EventEnvelope(
        id="evt_inb_bulk_1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_evt_inb_bulk_1",
        trace_id="tr_01",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream_name": "meter_reads",
            "record_ids": ["inb_1", "inb_2"],
        },
    )
    action = await dispatcher.dispatch_envelope(envelope)
    assert action == ConsumerAction.ACK
    assert len(uow.replica_records.merged_candidates) == 2
    assert ("t_01", "idem_evt_inb_bulk_1") in uow.committed_idempotency_keys

    # 2. Duplicate delivery of same idempotency_key -> skipped with ACK
    prev_commits = uow.commit_count
    dup_action = await dispatcher.dispatch_envelope(envelope)
    assert dup_action == ConsumerAction.ACK
    assert uow.commit_count == prev_commits


@pytest.mark.asyncio
async def test_orchestrator_route_registry_normalize_chunk_bounded_concurrency_and_nack_rollback() -> (
    None
):
    """Verify replica_record.changed fan-out respects asyncio.Semaphore(3) and rolls back on NACK."""
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow)
    storage = FakeTieredStorage()

    normalize_exec = FakeNormalizeExecutor(delay_seconds=0.015)
    backfill_exec = FakeBackfillExecutor()
    stitch_disp = FakeStitchDispatcher()
    stitch_tick = FakeStitchTickExecutor()

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=uow_provider,
        normalize_use_case=normalize_exec,
        backfill_use_case=backfill_exec,
        tiered_storage=storage,
        stitch_dispatcher=stitch_disp,
        stitch_worker_tick=stitch_tick,
        max_chunk_concurrency=3,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    # 1. Dispatch 10 replica_ids in a single BULK chunk with Semaphore(3)
    rep_ids: list[JsonValue] = [f"rep_{i}" for i in range(10)]
    bulk_envelope = EventEnvelope(
        id="evt_rep_bulk_10",
        source="ip.data_plane",
        event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_rep_bulk_10",
        trace_id="tr_bulk_10",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "meter_reads",
            "record_ids": rep_ids,
        },
    )
    action = await dispatcher.dispatch_envelope(bulk_envelope)
    assert action == ConsumerAction.ACK
    assert len(normalize_exec.executed_ids) == 10
    assert 1 < normalize_exec.max_observed_in_flight <= 3

    # 2. Transient failure on one item -> returns NACK and rolls back idempotency key
    normalize_exec.fail_ids.add("rep_fail")
    fail_envelope = EventEnvelope(
        id="evt_rep_fail",
        source="ip.data_plane",
        event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_rep_fail",
        trace_id="tr_fail",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "stream": "meter_reads",
            "record_ids": ["rep_ok", "rep_fail"],
        },
    )
    fail_action = await dispatcher.dispatch_envelope(fail_envelope)
    assert fail_action == ConsumerAction.NACK
    assert uow.release_count >= 1
    assert ("t_01", "idem_rep_fail") not in uow.committed_idempotency_keys


@pytest.mark.asyncio
async def test_orchestrator_route_registry_canonical_stitch_dispatch_and_generation_sweep() -> None:
    """Verify canonical_record.changed triggers L4 stitch dispatch + inline tick, plus generation sweep & backfill."""
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow)
    storage = FakeTieredStorage()
    normalize_exec = FakeNormalizeExecutor()
    backfill_exec = FakeBackfillExecutor()
    stitch_disp = FakeStitchDispatcher(started_run_ids=("wf_run_01",))
    stitch_tick = FakeStitchTickExecutor()

    registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=uow_provider,
        normalize_use_case=normalize_exec,
        backfill_use_case=backfill_exec,
        tiered_storage=storage,
        stitch_dispatcher=stitch_disp,
        stitch_worker_tick=stitch_tick,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    # 1. CanonicalRecordChanged -> L4 Stitch dispatch + inline tick
    canon_env = EventEnvelope(
        id="evt_canon_1",
        source="ip.data_plane",
        event_type=IpEventType.CANONICAL_RECORD_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_canon_1",
        trace_id="tr_canon_1",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "canonical_type": "energy.meter_reading.v1",
            "record_ids": ["MTR-1", "MTR-2"],
        },
    )
    assert await dispatcher.dispatch_envelope(canon_env) == ConsumerAction.ACK
    assert len(stitch_disp.commands) == 2
    assert len(stitch_tick.commands) == 2

    # 2. GenerationCompleted -> SweepStaleReplicasUseCase
    gen_env = EventEnvelope(
        id="evt_gen_1",
        source="ip.data_plane",
        event_type=IpEventType.GENERATION_COMPLETED.value,
        tenant_id="t_01",
        idempotency_key="idem_gen_1",
        trace_id="tr_gen_1",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "meter_reads",
            "generation_id": 5,
        },
    )
    assert await dispatcher.dispatch_envelope(gen_env) == ConsumerAction.ACK

    # 3. TransformationVersionPromoted -> BackfillStreamNormalizationUseCase
    bf_env = EventEnvelope(
        id="evt_bf_1",
        source="ip.control_plane",
        event_type=IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
        tenant_id="t_01",
        idempotency_key="idem_bf_1",
        trace_id="tr_bf_1",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "meter_reads",
            "transformation_id": "map_01",
        },
    )
    assert await dispatcher.dispatch_envelope(bf_env) == ConsumerAction.ACK
    assert len(backfill_exec.commands) == 1


# ==============================================================================
# 4. IpDeliveryRouteRegistry Tests (L5 Outbound Delivery & L1 Fetch/Sync)
# ==============================================================================


def _make_outbound_record(
    record_id: str,
    *,
    status: OutboundDispatchStatus = OutboundDispatchStatus.PENDING,
    is_inlined: bool = True,
    request_body: JsonDict | None = None,
    request_s3_key: str | None = None,
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
        status=status,
    )
    rec.id = record_id
    return rec


@pytest.mark.asyncio
async def test_delivery_route_registry_filters_pending_and_hydrates_s3_and_bounds_concurrency() -> (
    None
):
    """Verify IpDeliveryRouteRegistry filters out DELIVERED records, hydrates S3 payloads, and bounds concurrency."""
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow)
    storage = FakeTieredStorage()

    # Seed 4 PENDING records (one S3-offloaded) and 1 already DELIVERED record
    s3_body = {"invoice_id": "INV-S3", "total": 999.0}
    storage.blobs["s3://ip/out_s3.json"] = json.dumps(s3_body).encode("utf-8")

    uow.outbound_records.records["out_1"] = _make_outbound_record("out_1")
    uow.outbound_records.records["out_2"] = _make_outbound_record("out_2")
    uow.outbound_records.records["out_3"] = _make_outbound_record("out_3")
    uow.outbound_records.records["out_s3"] = _make_outbound_record(
        "out_s3",
        is_inlined=False,
        request_body=None,
        request_s3_key="s3://ip/out_s3.json",
    )
    uow.outbound_records.records["out_already_delivered"] = _make_outbound_record(
        "out_already_delivered",
        status=OutboundDispatchStatus.DELIVERED,
    )

    delivery_exec = FakeOutboundDeliveryExecutor(delay_seconds=0.015)
    fetch_exec = FakeFetchRecordExecutor()
    sync_exec = FakeRunSyncExecutor(status=SyncRunStatus.SUCCEEDED.value)

    registry = IpDeliveryRouteRegistry(
        dp_uow_provider=uow_provider,
        deliver_outbound_use_case=delivery_exec,
        fetch_record_use_case=fetch_exec,
        run_sync_use_case=sync_exec,
        tiered_storage=storage,
        max_chunk_concurrency=2,
    )
    dispatcher = EventEnvelopeDispatcher()
    registry.register_routes(dispatcher)

    # 1. Dispatch chunk with 4 PENDING + 1 DELIVERED
    out_env = EventEnvelope(
        id="evt_out_chunk_1",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_out_chunk_1",
        trace_id="tr_out_01",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream_name": "erp_invoices",
            "record_ids": [
                "out_1",
                "out_2",
                "out_3",
                "out_s3",
                "out_already_delivered",
            ],
        },
    )
    action = await dispatcher.dispatch_envelope(out_env)
    assert action == ConsumerAction.ACK
    # Only the 4 PENDING records were dispatched to the external API
    dispatched_ids = [cmd.record_id for cmd in delivery_exec.commands]
    assert sorted(str(x) for x in dispatched_ids) == ["out_1", "out_2", "out_3", "out_s3"]
    # S3 payload was hydrated before dispatch
    s3_cmd = next(cmd for cmd in delivery_exec.commands if cmd.record_id == "out_s3")
    assert s3_cmd.payload == {"invoice_id": "INV-S3", "total": 999.0}
    # Concurrency stayed bounded by Semaphore(2)
    assert 1 < delivery_exec.max_observed_in_flight <= 2

    # 2. FetchRecordRequested chunk
    fetch_env = EventEnvelope(
        id="evt_fetch_1",
        source="ip.data_plane",
        event_type=IpEventType.FETCH_RECORD_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="idem_fetch_1",
        trace_id="tr_fetch_01",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "stream": "orders",
            "record_ids": ["ORD-10", "ORD-11"],
            "notice_inbound_record_id": "inb_notice_1",
        },
    )
    assert await dispatcher.dispatch_envelope(fetch_env) == ConsumerAction.ACK
    assert [c.record_id for c in fetch_exec.commands] == ["ORD-10", "ORD-11"]

    # 3. SyncRunRequested status mapping (SUCCEEDED -> ACK, RATE_LIMITED -> NACK, TERMINAL -> DLQ)
    sync_env = EventEnvelope(
        id="evt_sync_1",
        source="ip.control_plane",
        event_type=IpEventType.SYNC_RUN_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="idem_sync_1",
        trace_id="tr_sync_01",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "meters",
        },
    )
    assert await dispatcher.dispatch_envelope(sync_env) == ConsumerAction.ACK

    sync_exec.status = SyncRunStatus.FAILED.value
    sync_exec.error_code = "RATE_LIMITED"
    assert await dispatcher.dispatch_envelope(sync_env) == ConsumerAction.NACK

    sync_exec.error_code = "AUTH_INVALID"
    assert await dispatcher.dispatch_envelope(sync_env) == ConsumerAction.DLQ


# ==============================================================================
# 5. Outbox Publisher Factory & Jobs Workers & Registry Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_ip_outbox_routers_route_realtime_and_bulk_lanes_correctly() -> None:
    """Verify build_ip_cp_outbox_router and build_ip_dp_outbox_router route REALTIME vs BULK."""
    orch_rt = FakeOutboxPublisher()
    orch_bulk = FakeOutboxPublisher()
    deliv_rt = FakeOutboxPublisher()
    deliv_bulk = FakeOutboxPublisher()
    notif_pub = FakeOutboxPublisher()
    events_pub = FakeOutboxPublisher()

    cp_router = build_ip_cp_outbox_router(
        orchestrator_realtime_publisher=orch_rt,
        orchestrator_bulk_publisher=orch_bulk,
        delivery_realtime_publisher=deliv_rt,
        delivery_bulk_publisher=deliv_bulk,
        notification_publisher=notif_pub,
        events_topic_publisher=events_pub,
    )
    dp_router = build_ip_dp_outbox_router(
        orchestrator_realtime_publisher=orch_rt,
        orchestrator_bulk_publisher=orch_bulk,
        delivery_realtime_publisher=deliv_rt,
        delivery_bulk_publisher=deliv_bulk,
        notification_publisher=notif_pub,
        events_topic_publisher=events_pub,
    )

    rt_inb = EventEnvelope(
        id="e1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k1",
        payload={},
        lane=EventProcessingLane.REALTIME,
    )
    bulk_inb = EventEnvelope(
        id="e2",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k2",
        payload={},
        lane=EventProcessingLane.BULK,
    )
    rt_out = EventEnvelope(
        id="e3",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k3",
        payload={},
        lane=EventProcessingLane.REALTIME,
    )
    bulk_out = EventEnvelope(
        id="e4",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k4",
        payload={},
        lane=EventProcessingLane.BULK,
    )

    acked = await dp_router.publish_batch([rt_inb, bulk_inb, rt_out, bulk_out])
    assert sorted(acked) == ["e1", "e2", "e3", "e4"]
    assert [e.id for e in orch_rt.published] == ["e1"]
    assert [e.id for e in orch_bulk.published] == ["e2"]
    assert [e.id for e in deliv_rt.published] == ["e3"]
    assert [e.id for e in deliv_bulk.published] == ["e4"]

    sync_evt = EventEnvelope(
        id="e5",
        source="ip.control_plane",
        event_type=IpEventType.SYNC_RUN_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="k5",
        payload={},
        lane=EventProcessingLane.BULK,
    )
    await cp_router.publish(sync_evt)
    assert [e.id for e in deliv_bulk.published] == ["e4", "e5"]


def test_unified_worker_registry_resolves_all_four_ip_workers() -> None:
    """Verify unified-worker registry resolves all four IP LaunchableWorker modules."""
    assert isinstance(get_worker_instance("ip-orchestrator-worker"), IpOrchestratorWorkerModule)
    assert isinstance(get_worker_instance("ip-delivery-worker"), IpDeliveryWorkerModule)
    assert isinstance(get_worker_instance("ip-cp-jobs-worker"), IpCpJobsWorkerModule)
    assert isinstance(get_worker_instance("ip-dp-jobs-worker"), IpDpJobsWorkerModule)


@pytest.mark.asyncio
async def test_cp_and_dp_jobs_workers_scheduled_handlers() -> None:
    """Verify IpCpJobsWorkerModule and IpDpJobsWorkerModule execute sweeper and retention jobs."""
    fake_repo = FakeOutboxRepository(
        initial_events=[
            EventEnvelope(
                id="evt_stuck_1",
                source="ip.data_plane",
                event_type=IpEventType.INBOUND_RECORD_CREATED.value,
                tenant_id="t_01",
                idempotency_key="idem_stuck_1",
                payload={},
            )
        ]
    )
    fake_pub = FakeOutboxPublisher()
    fake_trace_ret = FakeTraceRetentionRepository()
    settings = IpEngineSettings(
        ip_control_plane_jobs_queue_url="",
        ip_data_plane_jobs_queue_url="",
    )

    cp_worker = IpCpJobsWorkerModule(publisher=fake_pub, settings=settings)
    cp_worker.cp_sweeper = OutboxSweeperUseCase(
        repository=fake_repo,
        publisher=fake_pub,
        max_concurrent_events=10,
    )
    cp_worker.cp_cleaner = OutboxCleanerUseCase(
        repository=fake_repo,
        retention_days=7,
    )
    cp_worker._wire_jobs_consumer(settings)
    assert cp_worker.job_dispatcher is not None

    await cp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_CONTROL_PLANE_OUTBOX_SWEEPER.value}
    )
    assert len(fake_pub.published) == 1
    assert fake_repo.completed_batches == [["evt_stuck_1"]]

    await cp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_CONTROL_PLANE_OUTBOX_CLEANUP.value}
    )
    assert fake_repo.cleaned_retention_days == [7]

    dp_worker = IpDpJobsWorkerModule(publisher=fake_pub, settings=settings)
    dp_worker.dp_sweeper = OutboxSweeperUseCase(
        repository=fake_repo,
        publisher=fake_pub,
        max_concurrent_events=10,
    )
    dp_worker.dp_cleaner = OutboxCleanerUseCase(
        repository=fake_repo,
        retention_days=7,
    )
    dp_worker.trace_retention_use_case = CleanTraceRetentionUseCase(
        repository=fake_trace_ret,
    )
    dp_worker._wire_jobs_consumer(settings, retention_days=14)
    assert dp_worker.job_dispatcher is not None

    await dp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_DATA_PLANE_OUTBOX_SWEEPER.value}
    )
    await dp_worker.job_dispatcher.dispatch(
        {"job_name": IpJobName.IP_DATA_PLANE_OUTBOX_CLEANUP.value}
    )
    await dp_worker.job_dispatcher.dispatch({"job_name": IpJobName.IP_DATA_RETENTION_CLEANUP.value})
    assert len(fake_trace_ret.trace_retention_days) == 1
    assert fake_trace_ret.processed_retention_days == [14]

    await cp_worker.stop()
    await dp_worker.stop()


@pytest.mark.asyncio
async def test_multi_shard_stitch_tick_loop_lifecycle_and_single_tick() -> None:
    """Verify IpMultiShardStitchTickLoop start, background_tasks, run_single_tick, and stop."""
    tick_exec = FakeStitchTickExecutor()
    loop = IpMultiShardStitchTickLoop(
        tick_executor=tick_exec,
        worker_id="ip-orchestrator-test",
        free_slots=10,
        interval_seconds=0.05,
    )
    assert loop.background_tasks() == []

    dto = await loop.run_single_tick()
    assert dto is not None
    assert dto.completed_step_ids == ("step_01",)

    loop.start()
    assert loop.is_running is True
    assert len(loop.background_tasks()) == 1
    await asyncio.sleep(0.08)
    await loop.stop()
    assert loop.is_running is False
    assert loop.background_tasks() == []
    assert len(tick_exec.commands) >= 2


@pytest.mark.asyncio
async def test_orchestrator_and_delivery_additional_routes_and_error_branches() -> None:
    """Verify normalized_record.created, transformation.changed, and delivery error branches."""
    uow = FakeDataPlaneUoW()
    uow_provider = FakeDataPlaneUoWProvider(uow, missing_tenant_ids={"t_missing"})
    storage = FakeTieredStorage()
    normalize_exec = FakeNormalizeExecutor()
    backfill_exec = FakeBackfillExecutor()
    stitch_disp = FakeStitchDispatcher()
    stitch_tick = FakeStitchTickExecutor()

    orch_reg = IpOrchestratorRouteRegistry(
        dp_uow_provider=uow_provider,
        normalize_use_case=normalize_exec,
        backfill_use_case=backfill_exec,
        tiered_storage=storage,
        stitch_dispatcher=stitch_disp,
        stitch_worker_tick=stitch_tick,
    )
    dispatcher = EventEnvelopeDispatcher()
    orch_reg.register_routes(dispatcher)

    # 1. NormalizedRecordCreated route
    norm_rec = NormalizedRecord.create(
        tenant_id="t_01",
        connection_id="conn_01",
        canonical_type="energy.meter_reading.v1",
        source_id="MTR-55",
        canonical_data={"meter_id": "MTR-55", "kwh": 42.0},
        trace_id="tr_norm_1",
    )
    norm_rec.id = "norm_55"
    uow.normalized_records.records["norm_55"] = norm_rec

    norm_env = EventEnvelope(
        id="evt_norm_55",
        source="ip.data_plane",
        event_type=IpEventType.NORMALIZED_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_norm_55",
        trace_id="tr_norm_1",
        lane=EventProcessingLane.REALTIME,
        payload={
            "connection_id": "conn_01",
            "canonical_type": "energy.meter_reading.v1",
            "source_id": "MTR-55",
            "record_ids": ["norm_55"],
        },
    )
    assert await dispatcher.dispatch_envelope(norm_env) == ConsumerAction.ACK

    # 2. TransformationChanged route
    mb_env = EventEnvelope(
        id="evt_mb_1",
        source="ip.control_plane",
        event_type=IpEventType.TRANSFORMATION_CHANGED.value,
        tenant_id="t_01",
        idempotency_key="idem_mb_1",
        trace_id="tr_mb_1",
        lane=EventProcessingLane.BULK,
        payload={
            "connection_id": "conn_01",
            "stream": "meter_reads",
            "transformation_id": "map_02",
        },
    )
    assert await dispatcher.dispatch_envelope(mb_env) == ConsumerAction.ACK
    assert len(backfill_exec.commands) == 1

    # 3. Missing tenant shard returns DLQ
    missing_env = EventEnvelope(
        id="evt_missing_shard",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_missing",
        idempotency_key="idem_missing",
        payload={
            "connection_id": "conn_01",
            "stream_name": "meter_reads",
            "record_ids": ["inb_1"],
        },
    )
    assert await dispatcher.dispatch_envelope(missing_env) == ConsumerAction.DLQ

    # 4. Delivery route error dispositions (RATE_LIMITED -> NACK, TERMINAL -> DLQ)
    uow.outbound_records.records["out_rl"] = _make_outbound_record("out_rl")
    uow.outbound_records.records["out_term"] = _make_outbound_record("out_term")
    deliv_exec = FakeOutboundDeliveryExecutor(
        status_by_key={
            "idem_out_rl": OutboundDispatchStatus.RETRY_SCHEDULED,
            "idem_out_term": OutboundDispatchStatus.FAILED,
        }
    )
    deliv_reg = IpDeliveryRouteRegistry(
        dp_uow_provider=uow_provider,
        deliver_outbound_use_case=deliv_exec,
        fetch_record_use_case=FakeFetchRecordExecutor(status="RATE_LIMITED"),
        run_sync_use_case=FakeRunSyncExecutor(),
        tiered_storage=storage,
    )
    deliv_disp = EventEnvelopeDispatcher()
    deliv_reg.register_routes(deliv_disp)

    rl_env = EventEnvelope(
        id="evt_out_rl",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_evt_out_rl",
        payload={
            "connection_id": "conn_01",
            "stream_name": "erp_invoices",
            "record_ids": ["out_rl"],
        },
    )
    assert await deliv_disp.dispatch_envelope(rl_env) == ConsumerAction.NACK

    term_env = EventEnvelope(
        id="evt_out_term",
        source="ip.data_plane",
        event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="idem_evt_out_term",
        payload={
            "connection_id": "conn_01",
            "stream_name": "erp_invoices",
            "record_ids": ["out_term"],
        },
    )
    assert await deliv_disp.dispatch_envelope(term_env) == ConsumerAction.DLQ

    fetch_retry_env = EventEnvelope(
        id="evt_fetch_retry",
        source="ip.data_plane",
        event_type=IpEventType.FETCH_RECORD_REQUESTED.value,
        tenant_id="t_01",
        idempotency_key="idem_fetch_retry",
        payload={
            "connection_id": "conn_01",
            "stream": "orders",
            "record_ids": ["ORD-99"],
        },
    )
    assert await deliv_disp.dispatch_envelope(fetch_retry_env) == ConsumerAction.NACK
