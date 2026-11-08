"""Unit tests for ProcessInboundRangeUseCase verifying single-transaction L2-to-L3 atomicity."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.normalization.process_inbound_range_use_case import (
    ProcessInboundRangeCommand,
    ProcessInboundRangeUseCase,
)
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.domain.normalization.enums import NormalizationOutcome, TransformationMode
from ip.engine.domain.normalization.ledger import (
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.normalization.policies import DefaultNormalizationErrorPolicy
from ip.engine.domain.normalization.registries import (
    CanonicalEntityRegistry,
    CanonicalWriterRegistry,
    TransformerRegistry,
)
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    ReplicaSnapshot,
    Transformation,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.replication.enums import CursorKind, MergeOutcome, SyncMode
from ip.engine.domain.replication.inbound_record import InboundBatchItemSpec, InboundRecord
from ip.engine.domain.replication.replica_record import (
    ReplicaMergePolicy,
    ReplicaRecord,
    ReplicaRejection,
)
from ip.engine.domain.replication.stream_definition import StreamDefinition
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
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
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import TransformationRepositoryPort
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.engine.ports.outbound.uow import (
    DomainRepositoryKey,
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
    TDomainRepo,
)
from seedwork.domain.types import JsonDict
from seedwork.events import DomainEvent
from strace.domain import TraceEvent, TraceLineageItemDTO, TraceStatus
from strace.ports import TraceRepositoryPort


class _InMemoryInboundRepo(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}
        self.range_query_count = 0

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def save_batch(self, records: Sequence[InboundRecord]) -> None:
        for rec in records:
            self.records[rec.id] = rec

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(
        self, trace_id: str, tenant_id: str, *, hydrate_payloads: bool = False
    ) -> Sequence[InboundRecord]:
        _ = hydrate_payloads
        return [
            r for r in self.records.values() if r.tenant_id == tenant_id and r.trace_id == trace_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
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
        self.range_query_count += 1
        if batch_id and range_start and range_end:
            matched = [
                r
                for r in self.records.values()
                if r.tenant_id == tenant_id
                and r.batch_id == batch_id
                and range_start <= r.id <= range_end
            ]
            return sorted(matched, key=lambda r: (r.batch_seq, r.id))
        target_ids = list(record_ids) or ([range_start] if range_start else [])
        return [
            self.records[rec_id]
            for rec_id in target_ids
            if rec_id in self.records and self.records[rec_id].tenant_id == tenant_id
        ]


class _TransactionalReplicaRepo(ReplicaRecordRepositoryPort):
    def __init__(self, outbox: list[DomainEvent], traces: list[TraceEvent]) -> None:
        self.committed: dict[str, ReplicaRecord] = {}
        self.staged: dict[str, ReplicaRecord] = {}
        self._outbox = outbox
        self._traces = traces

    def _effective_by_key(
        self, tenant_id: str, connection_id: str, stream: str, record_key: str
    ) -> ReplicaRecord | None:
        merged = {**self.committed, **self.staged}
        for rec in merged.values():
            if (
                rec.tenant_id == tenant_id
                and rec.connection_id == connection_id
                and rec.stream == stream
                and rec.record_key == record_key
            ):
                return rec
        return None

    async def save(self, record: ReplicaRecord) -> None:
        self.staged[record.id] = record

    async def get_by_id(self, tenant_id: str, record_id: str) -> ReplicaRecord | None:
        merged = {**self.committed, **self.staged}
        rec = merged.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_key(
        self, tenant_id: str, connection_id: str, stream: str, record_key: str
    ) -> ReplicaRecord | None:
        return self._effective_by_key(tenant_id, connection_id, stream, record_key)

    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
        *,
        event_policy: ReplicationEventPolicyPort | None = None,
    ) -> list[MergeResult]:
        now = datetime.now(UTC)
        results: list[MergeResult] = []
        changed: list[ReplicaRecord] = []

        for c in candidates:
            existing = self._effective_by_key(c.tenant_id, c.connection_id, c.stream, c.record_key)
            cursor_kind = CursorKind(c.cursor_kind) if c.cursor_kind else CursorKind.STRING
            outcome = ReplicaMergePolicy.evaluate(
                existing=existing,
                incoming_data_hash=c.data_hash,
                incoming_cursor=c.cursor_value,
                cursor_kind=cursor_kind,
                is_deleted=c.is_deleted,
            )
            if outcome == MergeOutcome.INSERT:
                rec = ReplicaRecord.create(
                    tenant_id=c.tenant_id,
                    connection_id=c.connection_id,
                    stream=c.stream,
                    record_key=c.record_key,
                    primary_key_values=c.primary_key_values,
                    cursor_value=c.cursor_value,
                    cursor_kind=c.cursor_kind,
                    data=c.data,
                    generation_id=c.generation_id,
                    source_inbound_record_id=c.source_inbound_record_id,
                    trace_id=c.trace_id,
                    correlation_id=c.correlation_id,
                )
                self.staged[rec.id] = rec
                changed.append(rec)
                results.append(
                    MergeResult(
                        record_id=rec.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=MergeOutcome.INSERT,
                        version=rec.version,
                        data_hash=rec.data_hash,
                        replica=rec,
                    )
                )
            elif outcome == MergeOutcome.UPDATE and existing is not None:
                existing.update_snapshot(
                    new_data=c.data,
                    trace_id=c.trace_id,
                    correlation_id=c.correlation_id,
                    cursor_value=c.cursor_value,
                    generation_id=c.generation_id,
                    source_inbound_record_id=c.source_inbound_record_id,
                )
                self.staged[existing.id] = existing
                changed.append(existing)
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=MergeOutcome.UPDATE,
                        version=existing.version,
                        data_hash=existing.data_hash,
                        replica=existing,
                    )
                )
            else:
                assert existing is not None
                if outcome == MergeOutcome.NOOP:
                    existing.last_seen_generation = c.generation_id
                    existing.extracted_at = now
                    existing.updated_at = now
                    self.staged[existing.id] = existing
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=outcome,
                        version=existing.version,
                        data_hash=existing.data_hash,
                        replica=existing,
                    )
                )

        for agg in changed:
            self._traces.extend(agg.trace_events)
            agg.clear_trace_events()

        to_emit = (
            event_policy.select_outbox_replicas(changed)
            if event_policy is not None
            else tuple(changed)
        )
        for agg in to_emit:
            self._outbox.extend(agg.domain_events)
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
        _ = (tenant_id, connection_id, stream, current_generation, limit, trace_id)
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
        _ = (tenant_id, connection_id, stream, after_id, limit)
        return []

    def commit(self) -> None:
        self.committed.update(self.staged)
        self.staged.clear()

    def rollback(self) -> None:
        self.staged.clear()


class _FakeRejectionRepo(ReplicaRejectionRepositoryPort):
    def __init__(self) -> None:
        self.saved: list[ReplicaRejection] = []

    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        self.saved.extend(rejections)


class _FakeNormalizedRepo(NormalizedRecordRepositoryPort):
    def __init__(self, outbox: list[DomainEvent]) -> None:
        self.committed: dict[str, NormalizedRecord] = {}
        self.staged: dict[str, NormalizedRecord] = {}
        self._outbox = outbox

    async def save(self, record: NormalizedRecord) -> None:
        self.staged[record.id] = record
        if record.replay_count > 0:
            self._outbox.extend(record.domain_events)
        record.clear_domain_events()

    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        merged = {**self.committed, **self.staged}
        rec = merged.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def list_by_source(
        self, tenant_id: str, canonical_type: str, source_id: str
    ) -> Sequence[NormalizedRecord]:
        merged = {**self.committed, **self.staged}
        return [
            r
            for r in merged.values()
            if r.tenant_id == tenant_id
            and r.canonical_type == canonical_type
            and r.source_id == source_id
        ]

    def commit(self) -> None:
        self.committed.update(self.staged)
        self.staged.clear()

    def rollback(self) -> None:
        self.staged.clear()


class _FakeTraceRepo(TraceRepositoryPort):
    def __init__(self, sink: list[TraceEvent]) -> None:
        self.events = sink

    async def list_trace_events(self, tenant_id: str, trace_id: str) -> list[TraceEvent]:
        return [e for e in self.events if e.tenant_id == tenant_id and e.trace_id == trace_id]

    async def save_trace_event(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def save_all_trace_events(self, events: Sequence[TraceEvent]) -> None:
        self.events.extend(events)

    async def resolve_root_trace_id(self, tenant_id: str, trace_id: str) -> str:
        _ = tenant_id
        return trace_id

    async def get_trace_lineage(self, tenant_id: str, trace_id: str) -> list[TraceLineageItemDTO]:
        _ = (tenant_id, trace_id)
        return []

    async def find_traces_by_correlation_id(
        self, tenant_id: str, correlation_id: str, *, limit: int = 50
    ) -> list[TraceLineageItemDTO]:
        _ = (tenant_id, correlation_id, limit)
        return []

    async def list_recent_traces(
        self,
        tenant_id: str,
        *,
        status: TraceStatus | None = None,
        min_replay_count: int | None = None,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        _ = (tenant_id, status, min_replay_count, limit)
        return []


class _TransactionalLedgerRepo(NormalizationLedgerRepositoryPort):
    def __init__(self, outbox: list[DomainEvent], traces: list[TraceEvent]) -> None:
        self.committed: dict[tuple[str, str, str, int], NormalizationLedgerEntry] = {}
        self.staged: dict[tuple[str, str, str, int], NormalizationLedgerEntry] = {}
        self._outbox = outbox
        self._traces = traces

    async def get_latest_version(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> int | None:
        merged = {**self.committed, **self.staged}
        entry = merged.get(
            (tenant_id, replica_record_id, transformation_id, transformation_version)
        )
        return entry.replica_version if entry else None

    async def get_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> tuple[tuple[str, str], ...]:
        merged = {**self.committed, **self.staged}
        entry = merged.get(
            (tenant_id, replica_record_id, transformation_id, transformation_version)
        )
        return entry.produced_canonical_refs if entry else ()

    async def get_latest_produced_refs(
        self, *, tenant_id: str, replica_record_id: str, transformation_id: str
    ) -> tuple[tuple[str, str], ...]:
        merged = {**self.committed, **self.staged}
        matches = [
            e
            for e in merged.values()
            if e.tenant_id == tenant_id
            and e.replica_record_id == replica_record_id
            and e.transformation_id == transformation_id
        ]
        return matches[-1].produced_canonical_refs if matches else ()

    async def record_entry(self, entry: NormalizationLedgerEntry) -> None:
        key = (
            entry.tenant_id,
            entry.replica_record_id,
            entry.transformation_id,
            entry.transformation_version,
        )
        self.staged[key] = entry
        self._outbox.extend(entry.domain_events)
        entry.clear_domain_events()
        self._traces.extend(entry.trace_events)
        entry.clear_trace_events()

    def commit(self) -> None:
        self.committed.update(self.staged)
        self.staged.clear()

    def rollback(self) -> None:
        self.staged.clear()


class _FakeNormRejectionRepo(NormalizationRejectionRepositoryPort):
    def __init__(self) -> None:
        self.rejections: list[NormalizationRejectionEntry] = []
        self.shadow_diffs: list[NormalizationShadowDiffEntry] = []

    async def record_rejection(self, rejection: NormalizationRejectionEntry) -> None:
        self.rejections.append(rejection)

    async def record_shadow_diff(self, diff: NormalizationShadowDiffEntry) -> None:
        self.shadow_diffs.append(diff)


class _FakePendingRefRepo(PendingReferenceRepositoryPort):
    async def record_pending(self, entry: PendingReferenceEntry) -> None:
        _ = entry

    async def resolve_pending_for_target(
        self,
        *,
        tenant_id: str,
        source_connection_id: str,
        target_canonical_type: str,
        target_source_id: str,
    ) -> list[PendingReferenceEntry]:
        _ = (tenant_id, source_connection_id, target_canonical_type, target_source_id)
        return []


class _TransactionalDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort
    quarantine_records: QuarantineRecordRepositoryPort

    def __init__(self) -> None:
        self.staged_outbox: list[DomainEvent] = []
        self.committed_outbox: list[DomainEvent] = []
        self.staged_traces: list[TraceEvent] = []
        self.committed_traces: list[TraceEvent] = []
        self.inbound_records = _InMemoryInboundRepo()
        self.replica_records = _TransactionalReplicaRepo(self.staged_outbox, self.staged_traces)
        self.replica_rejections = _FakeRejectionRepo()
        self.normalized_records = _FakeNormalizedRepo(self.staged_outbox)
        self.normalization_ledger = _TransactionalLedgerRepo(self.staged_outbox, self.staged_traces)
        self.normalization_rejections = _FakeNormRejectionRepo()
        self.pending_references = _FakePendingRefRepo()
        self.traces = _FakeTraceRepo(self.staged_traces)
        self.commit_count = 0
        self.rollback_count = 0
        self._committed_in_scope = False

    async def __aenter__(self) -> _TransactionalDataPlaneUoW:
        self._committed_in_scope = False
        return self

    async def __aexit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None or not self._committed_in_scope:
            await self.rollback()

    async def commit(self) -> None:
        self._committed_in_scope = True
        self.commit_count += 1
        self.replica_records.commit()
        self.normalized_records.commit()
        self.normalization_ledger.commit()
        self.committed_outbox.extend(self.staged_outbox)
        self.staged_outbox.clear()
        self.committed_traces.extend(self.staged_traces)
        self.staged_traces.clear()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.replica_records.rollback()
        self.normalized_records.rollback()
        self.normalization_ledger.rollback()
        self.staged_outbox.clear()
        self.staged_traces.clear()

    def resolve_domain_repository(
        self, key: DomainRepositoryKey[TDomainRepo]
    ) -> TDomainRepo | None:
        _ = key
        return None


class _FakeDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, uow: _TransactionalDataPlaneUoW) -> None:
        self._uow = uow

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        _ = tenant_id
        return Result.ok(("shard_01", "in_memory_shard_dsn"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, shard_id: str, shard_dsn: str
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (tenant_id, shard_id, shard_dsn)
        async with self._uow as uow:
            yield uow


class _FakeTransformationRepo(TransformationRepositoryPort):
    def __init__(self, mapping: dict[tuple[str, str, str], Transformation]) -> None:
        self._mapping = mapping

    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> Transformation | None:
        return self._mapping.get((tenant_id, connection_id, stream))

    async def save(self, transformation: Transformation) -> None:
        self._mapping[
            (transformation.tenant_id, transformation.connection_id, transformation.stream)
        ] = transformation

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> Sequence[Transformation]:
        return [
            t
            for (tid, cid, _), t in self._mapping.items()
            if tid == tenant_id and cid == connection_id
        ]


class _FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    catalog: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self, transformations: dict[tuple[str, str, str], Transformation]) -> None:
        self.transformations = _FakeTransformationRepo(transformations)

    async def __aenter__(self) -> _FakeControlPlaneUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _OrderTransformer(TransformerPort):
    def __init__(self, *, fail_transient: bool = False) -> None:
        self.call_count = 0
        self._fail_transient = fail_transient

    @property
    def transformation_id(self) -> str:
        return "crm_order_to_canonical_v1"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.order.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        _ = context
        self.call_count += 1
        if self._fail_transient:
            raise TimeoutError("Transient lookup failure during L3 normalization")
        order_id = str(replica.data["id"])
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="canonical.order.v1",
                    source_id=order_id,
                    fields={"order_id": order_id, "total": replica.data.get("total", 0.0)},
                ),
            )
        )


class _OrderCanonicalWriter(CanonicalWriterPort):
    def __init__(self) -> None:
        self.staged_rows: dict[str, JsonDict] = {}

    @property
    def canonical_type(self) -> str:
        return "canonical.order.v1"

    async def upsert(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        transformation_id: str,
        transformation_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        _ = (extensions, transformation_id, transformation_version, replica_id, replica_version)
        norm = NormalizedRecord.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            canonical_type=self.canonical_type,
            source_id=source_id,
            canonical_data=dict(fields),
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        await uow.normalized_records.save(norm)
        self.staged_rows[source_id] = dict(fields)

    async def soft_delete(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        _ = (uow, tenant_id, connection_id, trace_id, correlation_id)
        self.staged_rows.pop(source_id, None)

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        _ = (uow, tenant_id, connection_id)
        return f"canon_{source_id}" if source_id in self.staged_rows else None

    async def resolve_reference(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        field_name: str,
        target_id: str,
        trace_id: str,
    ) -> None:
        _ = (uow, tenant_id, connection_id, source_id, field_name, target_id, trace_id)


def _build_fused_harness(
    *, fail_transient: bool = False
) -> tuple[
    _TransactionalDataPlaneUoW,
    _OrderTransformer,
    _OrderCanonicalWriter,
    ProcessInboundRangeUseCase,
]:
    dp_uow = _TransactionalDataPlaneUoW()
    dp_provider = _FakeDataPlaneUoWProvider(dp_uow)
    transformation = Transformation.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="orders",
        transformation_id="crm_order_to_canonical_v1",
        transformation_version=1,
        mode=TransformationMode.ACTIVE,
    )
    cp_uow = _FakeControlPlaneUoW({("ten_01", "conn_01", "orders"): transformation})

    transformer = _OrderTransformer(fail_transient=fail_transient)
    transformer_reg = TransformerRegistry()
    transformer_reg.register(transformer)

    writer = _OrderCanonicalWriter()
    writer_reg: CanonicalWriterRegistry[CanonicalWriterPort] = CanonicalWriterRegistry()
    writer_reg.register(writer)

    entity_reg = CanonicalEntityRegistry()
    entity_reg.register(
        CanonicalEntityDefinition(canonical_type="canonical.order.v1", schema_version=1)
    )

    normalize_uc = NormalizeReplicaRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_provider,
        transformer_registry=transformer_reg,
        writer_registry=writer_reg,
        entity_registry=entity_reg,
        error_policy=DefaultNormalizationErrorPolicy(),
    )
    fused_uc = ProcessInboundRangeUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_provider,
        normalize_use_case=normalize_uc,
    )
    return dp_uow, transformer, writer, fused_uc


@pytest.mark.asyncio
async def test_process_inbound_range_commits_l2_with_l3_in_single_transaction() -> None:
    dp_uow, transformer, writer, fused_uc = _build_fused_harness()
    payload: JsonDict = {"id": "ORD-100", "total": 250.0, "updated_at": "2026-10-27T10:00:00Z"}
    inbound = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="crm_source",
        stream_name="orders",
        payload_bytes=json.dumps(payload).encode("utf-8"),
        is_inlined=True,
        request_body=payload,
        trace_id="ip_trc_fused_1",
    )
    await dp_uow.inbound_records.save(inbound)

    res = await fused_uc.execute(
        ProcessInboundRangeCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="orders",
            batch_id=inbound.batch_id,
            range_start=inbound.id,
            range_end=inbound.id,
            count=1,
            generation_id=1,
            trace_id="ip_trc_fused_1",
            stream_definition=StreamDefinition(
                stream="orders",
                primary_key=(("id",),),
                cursor_field=("updated_at",),
                cursor_kind=CursorKind.STRING,
                sync_mode=SyncMode.INCREMENTAL,
            ),
        )
    )

    assert res.is_ok
    dto = res.unwrap()
    assert dp_uow.commit_count == 1
    assert dto.replication_summary.inserted_count == 1
    assert transformer.call_count == 1
    assert "ORD-100" in writer.staged_rows
    assert len(dp_uow.replica_records.committed) == 1
    assert len(dp_uow.normalized_records.committed) == 1
    assert dp_uow.committed_outbox == []
    assert len(dto.canonical_changes) == 1
    assert dto.canonical_changes[0].canonical_type == "canonical.order.v1"
    assert dto.canonical_changes[0].source_id == "ORD-100"
    assert dto.canonical_changes[0].outcome == NormalizationOutcome.NORMALIZED


@pytest.mark.asyncio
async def test_process_inbound_range_short_circuits_on_l2_hash_match() -> None:
    dp_uow, transformer, _, fused_uc = _build_fused_harness()
    payload: JsonDict = {"id": "ORD-200", "total": 99.0}
    raw_bytes = json.dumps(payload).encode("utf-8")

    first = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="crm_source",
        stream_name="orders",
        payload_bytes=raw_bytes,
        is_inlined=True,
        request_body=payload,
        trace_id="ip_trc_first",
    )
    await dp_uow.inbound_records.save(first)
    first_res = await fused_uc.execute(
        ProcessInboundRangeCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="orders",
            batch_id=first.batch_id,
            range_start=first.id,
            range_end=first.id,
            count=1,
            generation_id=1,
            trace_id="ip_trc_first",
        )
    )
    assert first_res.is_ok
    assert transformer.call_count == 1

    duplicate = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="crm_source",
        stream_name="orders",
        payload_bytes=raw_bytes,
        is_inlined=True,
        request_body=payload,
        trace_id="ip_trc_dup",
    )
    await dp_uow.inbound_records.save(duplicate)
    dup_res = await fused_uc.execute(
        ProcessInboundRangeCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="orders",
            batch_id=duplicate.batch_id,
            range_start=duplicate.id,
            range_end=duplicate.id,
            count=1,
            generation_id=2,
            trace_id="ip_trc_dup",
        )
    )

    assert dup_res.is_ok
    dup_dto = dup_res.unwrap()
    assert dup_dto.replication_summary.noop_count == 1
    assert dup_dto.canonical_changes == ()
    assert transformer.call_count == 1
    saved_rep = next(iter(dp_uow.replica_records.committed.values()))
    assert saved_rep.last_seen_generation == 2


@pytest.mark.asyncio
async def test_process_inbound_range_rolls_back_l2_when_l3_fails_transiently() -> None:
    dp_uow, _, _, fused_uc = _build_fused_harness(fail_transient=True)
    payload: JsonDict = {"id": "ORD-500", "total": 500.0}
    inbound = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="crm_source",
        stream_name="orders",
        payload_bytes=json.dumps(payload).encode("utf-8"),
        is_inlined=True,
        request_body=payload,
        trace_id="ip_trc_fail",
    )
    await dp_uow.inbound_records.save(inbound)

    res = await fused_uc.execute(
        ProcessInboundRangeCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="orders",
            batch_id=inbound.batch_id,
            range_start=inbound.id,
            range_end=inbound.id,
            count=1,
            generation_id=1,
            trace_id="ip_trc_fail",
        )
    )

    assert res.is_err
    assert dp_uow.commit_count == 0
    assert dp_uow.rollback_count >= 1
    assert dp_uow.replica_records.committed == {}


@pytest.mark.asyncio
async def test_process_inbound_range_processes_bulk_range_in_single_commit() -> None:
    dp_uow, transformer, _, fused_uc = _build_fused_harness()
    specs = [
        InboundBatchItemSpec(
            payload_bytes=json.dumps({"id": f"ORD-B{i}", "total": 10.0 * i}).encode("utf-8"),
            is_inlined=True,
            request_body={"id": f"ORD-B{i}", "total": 10.0 * i},
        )
        for i in range(1, 4)
    ]
    records = InboundRecord.create_range_batch(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="crm_source",
        stream_name="orders",
        items=specs,
        trace_id="ip_trc_bulk_range",
    )
    await dp_uow.inbound_records.save_batch(records)

    res = await fused_uc.execute(
        ProcessInboundRangeCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="orders",
            batch_id=records[0].batch_id,
            range_start=records[0].id,
            range_end=records[-1].id,
            count=3,
            generation_id=1,
            trace_id="ip_trc_bulk_range",
        )
    )

    assert res.is_ok
    dto = res.unwrap()
    assert dp_uow.inbound_records.range_query_count == 1
    assert dp_uow.commit_count == 1
    assert transformer.call_count == 3
    assert [c.source_id for c in dto.canonical_changes] == ["ORD-B1", "ORD-B2", "ORD-B3"]
