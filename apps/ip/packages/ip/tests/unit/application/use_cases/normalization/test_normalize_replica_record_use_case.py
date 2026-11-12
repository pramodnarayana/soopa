"""Comprehensive unit tests for NormalizeReplicaRecordUseCase and BackfillStreamNormalizationUseCase."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordUseCase,
)
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.domain.normalization.enums import (
    CanonicalAction,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
    RuleSeverity,
    TransformationMode,
)
from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.normalization.ledger import (
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)
from ip.engine.domain.normalization.policies import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.normalization.registries import (
    CanonicalEntityRegistry,
    CanonicalWriterRegistry,
    TransformerRegistry,
)
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    ReplicaSnapshot,
    SourceReference,
    Transformation,
    TransformationContext,
    TransformationRejection,
    TransformationResult,
)
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.domain.trace.enums import IpTraceEventType
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.entity_map_repository_port import (
    GlobalEntityMapRepositoryPort,
)
from ip.engine.ports.outbound.inbound_record_repository_port import (
    InboundRecordRepositoryPort,
)
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import (
    OutboundRecordRepositoryPort,
)
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
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
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
from tests.helpers.worker_fakes import InMemoryBatchManifestRepo

# ---------------------------------------------------------------------------
# In-Memory Test Fakes
# ---------------------------------------------------------------------------


class FakeTransformationRepository(TransformationRepositoryPort):
    def __init__(self) -> None:
        self.transformations: dict[tuple[str, str, str], Transformation] = {}

    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> Transformation | None:
        return self.transformations.get((tenant_id, connection_id, stream))

    async def save(self, transformation: Transformation) -> None:
        self.transformations[
            (transformation.tenant_id, transformation.connection_id, transformation.stream)
        ] = transformation

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> list[Transformation]:
        return [
            b
            for b in self.transformations.values()
            if b.tenant_id == tenant_id and b.connection_id == connection_id
        ]


class FakeReplicaRecordRepository(ReplicaRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, ReplicaRecord] = {}
        self.events: list[DomainEvent] = []
        self.trace_events: list[TraceEvent] = []

    async def get_by_id(self, tenant_id: str, record_id: str) -> ReplicaRecord | None:
        rec = self.records.get(record_id)
        if rec and rec.tenant_id == tenant_id:
            return rec
        return None

    async def save(self, record: ReplicaRecord) -> None:
        self.records[record.id] = record
        self.events.extend(record.domain_events)
        record.clear_domain_events()
        self.trace_events.extend(record.trace_events)
        record.clear_trace_events()

    async def get_by_key(
        self, tenant_id: str, connection_id: str, stream: str, record_key: str
    ) -> ReplicaRecord | None:
        for r in self.records.values():
            if (
                r.tenant_id == tenant_id
                and r.connection_id == connection_id
                and r.stream == stream
                and r.record_key == record_key
            ):
                return r
        return None

    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
        *,
        event_policy: ReplicationEventPolicyPort | None = None,
    ) -> list[MergeResult]:
        _ = (candidates, event_policy)
        return []

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
        matching = sorted(
            (
                r
                for r in self.records.values()
                if r.tenant_id == tenant_id
                and r.connection_id == connection_id
                and r.stream == stream
                and (after_id is None or r.id > after_id)
            ),
            key=lambda r: r.id,
        )
        return matching[:limit]

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


class FakeTraceRepository(TraceRepositoryPort):
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def list_trace_events(self, tenant_id: str, trace_id: str) -> list[TraceEvent]:
        return [e for e in self.events if e.tenant_id == tenant_id and e.trace_id == trace_id]

    async def save_trace_event(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def save_all_trace_events(self, events: Sequence[TraceEvent]) -> None:
        self.events.extend(events)

    async def resolve_root_trace_id(self, tenant_id: str, trace_id: str) -> str:
        return trace_id

    async def get_trace_lineage(self, tenant_id: str, trace_id: str) -> list[TraceLineageItemDTO]:
        return []

    async def find_traces_by_correlation_id(
        self, tenant_id: str, correlation_id: str, *, limit: int = 50
    ) -> list[TraceLineageItemDTO]:
        return []

    async def list_recent_traces(
        self,
        tenant_id: str,
        *,
        status: TraceStatus | None = None,
        min_replay_count: int | None = None,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        return []


class FakeNormalizationLedgerRepository(NormalizationLedgerRepositoryPort):
    def __init__(self, trace_repo: FakeTraceRepository) -> None:
        self._trace_repo = trace_repo
        self.entries: dict[tuple[str, str, str, int], NormalizationLedgerEntry] = {}
        self.events: list[DomainEvent] = []

    async def get_latest_version(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> int | None:
        key = (tenant_id, replica_record_id, transformation_id, transformation_version)
        entry = self.entries.get(key)
        return entry.replica_version if entry else None

    async def get_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> tuple[tuple[str, str], ...]:
        key = (tenant_id, replica_record_id, transformation_id, transformation_version)
        entry = self.entries.get(key)
        return entry.produced_canonical_refs if entry else ()

    async def get_latest_produced_refs(
        self, *, tenant_id: str, replica_record_id: str, transformation_id: str
    ) -> tuple[tuple[str, str], ...]:
        matching = [
            e
            for e in self.entries.values()
            if e.tenant_id == tenant_id
            and e.replica_record_id == replica_record_id
            and e.transformation_id == transformation_id
            and e.outcome in (NormalizationOutcome.NORMALIZED, NormalizationOutcome.TOMBSTONED)
        ]
        if not matching:
            return ()
        matching.sort(key=lambda e: (e.created_at, e.replica_version), reverse=True)
        return matching[0].produced_canonical_refs

    async def record_entry(self, entry: NormalizationLedgerEntry) -> None:
        key = (
            entry.tenant_id,
            entry.replica_record_id,
            entry.transformation_id,
            entry.transformation_version,
        )
        self.entries[key] = entry
        self.events.extend(entry.domain_events)
        entry.clear_domain_events()
        self._trace_repo.events.extend(entry.trace_events)
        entry.clear_trace_events()


class FakeNormalizationRejectionRepository(NormalizationRejectionRepositoryPort):
    def __init__(self) -> None:
        self.rejections: list[NormalizationRejectionEntry] = []
        self.shadow_diffs: list[NormalizationShadowDiffEntry] = []

    async def record_rejection(self, rejection: NormalizationRejectionEntry) -> None:
        self.rejections.append(rejection)

    async def record_shadow_diff(self, diff: NormalizationShadowDiffEntry) -> None:
        self.shadow_diffs.append(diff)


class FakePendingReferenceRepository(PendingReferenceRepositoryPort):
    def __init__(self) -> None:
        self.pending: list[PendingReferenceEntry] = []

    async def record_pending(self, entry: PendingReferenceEntry) -> None:
        self.pending.append(entry)

    async def resolve_pending_for_target(
        self,
        *,
        tenant_id: str,
        source_connection_id: str,
        target_canonical_type: str,
        target_source_id: str,
    ) -> list[PendingReferenceEntry]:
        resolved: list[PendingReferenceEntry] = []
        updated_pending: list[PendingReferenceEntry] = []
        for p in self.pending:
            if (
                p.tenant_id == tenant_id
                and p.source_connection_id == source_connection_id
                and p.target_canonical_type == target_canonical_type
                and p.target_source_id == target_source_id
                and p.status == PendingReferenceStatus.PENDING
            ):
                resolved_entry = PendingReferenceEntry(
                    id=p.id,
                    tenant_id=p.tenant_id,
                    source_connection_id=p.source_connection_id,
                    target_canonical_type=p.target_canonical_type,
                    target_source_id=p.target_source_id,
                    referencing_canonical_type=p.referencing_canonical_type,
                    referencing_source_id=p.referencing_source_id,
                    referencing_field=p.referencing_field,
                    status=PendingReferenceStatus.RESOLVED,
                    trace_id=p.trace_id,
                    created_at=p.created_at,
                    resolved_at=datetime.now(UTC),
                )
                resolved.append(resolved_entry)
                updated_pending.append(resolved_entry)
            else:
                updated_pending.append(p)
        self.pending = updated_pending
        return resolved


class FakeDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
    inbound_records: InboundRecordRepositoryPort
    replica_records: FakeReplicaRecordRepository
    replica_rejections: ReplicaRejectionRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort
    quarantine_records: QuarantineRecordRepositoryPort
    normalization_ledger: FakeNormalizationLedgerRepository
    normalization_rejections: FakeNormalizationRejectionRepository
    pending_references: FakePendingReferenceRepository
    traces: FakeTraceRepository
    batch_manifests: InMemoryBatchManifestRepo

    def __init__(self) -> None:
        self.traces = FakeTraceRepository()
        self.replica_records = FakeReplicaRecordRepository()
        self.normalization_ledger = FakeNormalizationLedgerRepository(self.traces)
        self.normalization_rejections = FakeNormalizationRejectionRepository()
        self.pending_references = FakePendingReferenceRepository()
        self.batch_manifests = InMemoryBatchManifestRepo()
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> FakeDataPlaneUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def resolve_domain_repository(
        self, key: DomainRepositoryKey[TDomainRepo]
    ) -> TDomainRepo | None:
        del key
        return None


class FakeDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, uow: FakeDataPlaneUoW) -> None:
        self.uow = uow

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        return Result.ok(("shard_1", "postgresql+asyncpg://dummy"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, shard_id: str, shard_dsn: str
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        yield self.uow


class FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    entities: ConnectionEntityRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: FakeTransformationRepository
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.transformations = FakeTransformationRepository()

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> FakeControlPlaneUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class RecordingCanonicalWriter(CanonicalWriterPort):
    def __init__(self, can_type: str) -> None:
        self._type = can_type
        self.upserted: list[tuple[str, JsonDict]] = []
        self.rows_by_source_id: dict[str, JsonDict] = {}
        self.soft_deleted: list[str] = []
        self.resolved_references: list[tuple[str, str, str]] = []

    @property
    def canonical_type(self) -> str:
        return self._type

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
        row_copy = dict(fields)
        self.upserted.append((source_id, row_copy))
        self.rows_by_source_id[source_id] = row_copy

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
        self.soft_deleted.append(source_id)
        self.rows_by_source_id.pop(source_id, None)

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        if source_id in self.rows_by_source_id:
            return f"canon_{self._type}_{source_id}"
        return None

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
        self.resolved_references.append((source_id, field_name, target_id))
        if source_id in self.rows_by_source_id:
            self.rows_by_source_id[source_id][field_name] = target_id


@dataclass(frozen=True)
class MockQualityRule:
    rule_code: str
    severity_level: RuleSeverity
    required_field: str

    @property
    def code(self) -> str:
        return self.rule_code

    @property
    def severity(self) -> RuleSeverity:
        return self.severity_level

    def evaluate(self, fields: JsonDict) -> str | None:
        if self.required_field not in fields or fields[self.required_field] is None:
            return f"Missing required field: {self.required_field}"
        return None


class SimpleTransformer(TransformerPort):
    def __init__(self, m_id: str, m_ver: int, multiplier: float = 1.0) -> None:
        self._id = m_id
        self._ver = m_ver
        self._multiplier = multiplier

    @property
    def transformation_id(self) -> str:
        return self._id

    @property
    def transformation_version(self) -> int:
        return self._ver

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.record_alpha",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        if replica.data.get("trigger_error"):
            raise ValueError("Invalid field format in payload")

        if replica.data.get("reject_flag"):
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED,
                        field_path="serial",
                        detail="Serial is blacklisted",
                    ),
                )
            )

        raw_val = replica.data.get("metric_value", 0.0)
        metric_val = float(raw_val) * self._multiplier if isinstance(raw_val, (int, float)) else 0.0
        target_parent = str(replica.data.get("parent_entity_source_id", "parent_999"))
        draft = CanonicalDraft(
            canonical_type="canonical.record_alpha",
            source_id=replica.record_key,
            fields={
                "metric_value": metric_val,
                "record_serial": replica.data.get("serial"),
            },
            references=(
                SourceReference(
                    field_name="parent_entity_id",
                    target_canonical_type="canonical.parent_entity",
                    target_source_id=target_parent,
                ),
            ),
        )
        return TransformationResult(drafts=(draft,))


class ParentEntityTransformer(TransformerPort):
    @property
    def transformation_id(self) -> str:
        return "synthetic.parent_entity"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.parent_entity",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        draft = CanonicalDraft(
            canonical_type="canonical.parent_entity",
            source_id=replica.record_key,
            fields={"region_code": replica.data.get("region_code", "US-EAST")},
        )
        return TransformationResult(drafts=(draft,))


# ---------------------------------------------------------------------------
# Fixtures & Tests
# ---------------------------------------------------------------------------


@dataclass
class NormalizationTestEnv:
    use_case: NormalizeReplicaRecordUseCase
    cp_uow: FakeControlPlaneUoW
    dp_uow: FakeDataPlaneUoW
    dp_provider: FakeDataPlaneUoWProvider
    writer: RecordingCanonicalWriter
    parent_writer: RecordingCanonicalWriter
    transformer_registry: TransformerRegistry
    writer_registry: CanonicalWriterRegistry[CanonicalWriterPort]
    entity_registry: CanonicalEntityRegistry


@pytest.fixture
def setup_env() -> NormalizationTestEnv:
    cp_uow = FakeControlPlaneUoW()
    dp_uow = FakeDataPlaneUoW()
    dp_provider = FakeDataPlaneUoWProvider(dp_uow)
    transformer_registry = TransformerRegistry()
    writer_registry: CanonicalWriterRegistry[CanonicalWriterPort] = CanonicalWriterRegistry()
    entity_registry = CanonicalEntityRegistry()
    error_policy = DefaultNormalizationErrorPolicy()

    transformer = SimpleTransformer("synthetic.record_alpha", 1)
    transformer_registry.register(transformer)
    transformer_registry.register(ParentEntityTransformer())

    writer = RecordingCanonicalWriter("canonical.record_alpha")
    parent_writer = RecordingCanonicalWriter("canonical.parent_entity")
    writer_registry.register(writer)
    writer_registry.register(parent_writer)

    use_case = NormalizeReplicaRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_provider,
        transformer_registry=transformer_registry,
        writer_registry=writer_registry,
        entity_registry=entity_registry,
        error_policy=error_policy,
    )

    return NormalizationTestEnv(
        use_case=use_case,
        cp_uow=cp_uow,
        dp_uow=dp_uow,
        dp_provider=dp_provider,
        writer=writer,
        parent_writer=parent_writer,
        transformer_registry=transformer_registry,
        writer_registry=writer_registry,
        entity_registry=entity_registry,
    )


@pytest.mark.asyncio
async def test_normalize_skipped_no_transformation(setup_env: NormalizationTestEnv) -> None:
    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        replica_record_id="rep_1",
        replica_version=1,
        trace_id="trc_1",
    )
    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    assert result.unwrap().outcome == NormalizationOutcome.SKIPPED_NO_TRANSFORMATION


@pytest.mark.asyncio
async def test_normalize_version_guard_skips_stale_replica_version(
    setup_env: NormalizationTestEnv,
) -> None:
    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
    )
    await setup_env.cp_uow.transformations.save(transformation)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_stale",
        data={"metric_value": 10.0},
        trace_id="trc_old",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    ledger_entry = NormalizationLedgerEntry.create(
        tenant_id="tenant_1",
        replica_record_id=replica.id,
        replica_version=3,
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
        produced_canonical_refs=(),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_old",
    )
    await setup_env.dp_uow.normalization_ledger.record_entry(ledger_entry)

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        replica_record_id=replica.id,
        replica_version=2,
        trace_id="trc_new",
    )
    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    assert result.unwrap().outcome == NormalizationOutcome.SKIPPED_STALE

    trace_types = [t.event_type for t in setup_env.dp_uow.traces.events]
    assert IpTraceEventType.SKIPPED_STALE.value in trace_types
    assert len(setup_env.dp_uow.replica_records.trace_events) == 0


@pytest.mark.asyncio
async def test_normalize_success_persists_canonical_draft(
    setup_env: NormalizationTestEnv,
) -> None:
    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
    )
    await setup_env.cp_uow.transformations.save(transformation)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_100",
        data={"metric_value": 105.4, "serial": "SN-REC-1"},
        trace_id="trc_1",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        replica_record_id=replica.id,
        replica_version=replica.version,
        trace_id="trc_1",
    )

    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.NORMALIZED
    assert dto.canonical_refs_produced == (("canonical.record_alpha", "rec_100"),)
    assert setup_env.dp_uow.committed

    assert len(setup_env.writer.upserted) == 1
    assert setup_env.writer.upserted[0][0] == "rec_100"
    assert setup_env.writer.upserted[0][1]["metric_value"] == 105.4

    assert len(setup_env.dp_uow.pending_references.pending) == 1
    pref = setup_env.dp_uow.pending_references.pending[0]
    assert pref.target_canonical_type == "canonical.parent_entity"
    assert pref.target_source_id == "parent_999"

    events = [
        e
        for e in setup_env.dp_uow.normalization_ledger.events
        if isinstance(e, CanonicalRecordChangedEvent)
    ]
    assert len(events) == 1
    assert events[0].action == CanonicalAction.UPSERT.value
    assert events[0].canonical_type == "canonical.record_alpha"
    assert events[0].source_id == "rec_100"
    assert len(setup_env.dp_uow.replica_records.trace_events) == 0

    trace_events = setup_env.dp_uow.traces.events
    trace_types = [t.event_type for t in trace_events]
    assert IpTraceEventType.REFERENCE_PENDING.value in trace_types
    assert IpTraceEventType.NORMALIZED.value in trace_types
    normalized_trace = next(
        t for t in trace_events if t.event_type == IpTraceEventType.NORMALIZED.value
    )
    assert normalized_trace.metadata is not None
    assert normalized_trace.metadata["transformation_id"] == "synthetic.record_alpha"
    assert normalized_trace.metadata["transformation_version"] == 1


@pytest.mark.asyncio
async def test_normalize_backpatches_pending_reference_on_late_target_arrival(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies Step 13 late-arriving back-patching when referenced entity arrives out of order."""
    await setup_env.cp_uow.transformations.save(
        Transformation.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            transformation_id="synthetic.record_alpha",
            transformation_version=1,
        )
    )
    await setup_env.cp_uow.transformations.save(
        Transformation.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="parent_entities",
            transformation_id="synthetic.parent_entity",
            transformation_version=1,
        )
    )

    child_rep = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_early",
        data={"metric_value": 42.0, "serial": "SN-1", "parent_entity_source_id": "parent_999"},
        trace_id="trc_early",
    )
    await setup_env.dp_uow.replica_records.save(child_rep)
    res1 = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            replica_record_id=child_rep.id,
            replica_version=child_rep.version,
            trace_id="trc_early",
        )
    )
    assert res1.is_ok
    assert "parent_entity_id" not in setup_env.writer.rows_by_source_id["rec_early"]
    assert len(setup_env.dp_uow.pending_references.pending) == 1

    parent_rep = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="parent_entities",
        record_key="parent_999",
        data={"region_code": "US-WEST"},
        trace_id="trc_parent",
    )
    await setup_env.dp_uow.replica_records.save(parent_rep)
    setup_env.dp_uow.traces.events.clear()

    res2 = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="parent_entities",
            replica_record_id=parent_rep.id,
            replica_version=parent_rep.version,
            trace_id="trc_parent",
        )
    )
    assert res2.is_ok
    assert res2.unwrap().resolved_references_count == 1
    assert setup_env.writer.resolved_references == [
        ("rec_early", "parent_entity_id", "canon_canonical.parent_entity_parent_999")
    ]
    assert (
        setup_env.writer.rows_by_source_id["rec_early"]["parent_entity_id"]
        == "canon_canonical.parent_entity_parent_999"
    )
    trace_types = [t.event_type for t in setup_env.dp_uow.traces.events]
    assert IpTraceEventType.REFERENCE_RESOLVED.value in trace_types


@pytest.mark.asyncio
async def test_normalize_resolves_reference_immediately_when_target_exists(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies Step 5 immediate reference resolution when referenced target already exists."""
    await setup_env.cp_uow.transformations.save(
        Transformation.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            transformation_id="synthetic.record_alpha",
            transformation_version=1,
        )
    )
    await setup_env.cp_uow.transformations.save(
        Transformation.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="parent_entities",
            transformation_id="synthetic.parent_entity",
            transformation_version=1,
        )
    )

    parent_rep = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="parent_entities",
        record_key="parent_999",
        data={"region_code": "US-WEST"},
        trace_id="trc_parent",
    )
    await setup_env.dp_uow.replica_records.save(parent_rep)
    await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="parent_entities",
            replica_record_id=parent_rep.id,
            replica_version=parent_rep.version,
            trace_id="trc_parent",
        )
    )

    child_rep = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_after_parent",
        data={"metric_value": 88.0, "serial": "SN-2", "parent_entity_source_id": "parent_999"},
        trace_id="trc_after",
    )
    await setup_env.dp_uow.replica_records.save(child_rep)
    res = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            replica_record_id=child_rep.id,
            replica_version=child_rep.version,
            trace_id="trc_after",
        )
    )
    assert res.is_ok
    assert (
        setup_env.writer.rows_by_source_id["rec_after_parent"]["parent_entity_id"]
        == "canon_canonical.parent_entity_parent_999"
    )
    assert len(setup_env.dp_uow.pending_references.pending) == 0


@pytest.mark.asyncio
async def test_normalize_shadow_mode_does_not_mutate_canonical_or_outbox(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies TransformationMode.SHADOW writes only shadow diffs and never mutates canonical tables or outbox."""
    # Register v2 transformer with 2.0 multiplier
    setup_env.transformer_registry.register(
        SimpleTransformer("synthetic.record_alpha", 2, multiplier=2.0)
    )

    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
        mode=TransformationMode.SHADOW,
        shadow_transformation_version=2,
    )
    await setup_env.cp_uow.transformations.save(transformation)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_shadow",
        data={"metric_value": 50.0, "serial": "SN-SHD"},
        trace_id="trc_shd",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.events.clear()
    setup_env.dp_uow.replica_records.trace_events.clear()

    result = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            replica_record_id=replica.id,
            replica_version=replica.version,
            trace_id="trc_shd",
        )
    )
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.NORMALIZED
    assert dto.canonical_refs_produced == ()
    assert dto.shadow_diff_count == 1

    # Canonical writer must NOT be called
    assert len(setup_env.writer.upserted) == 0
    # Normalization ledger and pending references must NOT be written
    assert len(setup_env.dp_uow.normalization_ledger.entries) == 0
    assert len(setup_env.dp_uow.pending_references.pending) == 0
    # Outbox CanonicalRecordChangedEvent must NOT be emitted
    assert len(setup_env.dp_uow.normalization_ledger.events) == 0
    assert len(setup_env.dp_uow.replica_records.events) == 0
    assert len(setup_env.dp_uow.traces.events) == 1
    # Shadow diff MUST be recorded
    assert len(setup_env.dp_uow.normalization_rejections.shadow_diffs) == 1
    diff_entry = setup_env.dp_uow.normalization_rejections.shadow_diffs[0]
    assert diff_entry.candidate_version == 2
    assert diff_entry.diff_data == {
        "canonical.record_alpha:rec_shadow": {
            "metric_value": {"active": 50.0, "shadow": 100.0},
        }
    }


@pytest.mark.asyncio
async def test_normalize_quality_rule_rejection(setup_env: NormalizationTestEnv) -> None:
    rule = MockQualityRule("REQ_SERIAL", RuleSeverity.REJECT, "record_serial")
    setup_env.entity_registry.register(
        CanonicalEntityDefinition(
            canonical_type="canonical.record_alpha",
            schema_version=1,
            quality_rules=(rule,),
        )
    )

    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
    )
    await setup_env.cp_uow.transformations.save(transformation)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_invalid",
        data={"metric_value": 50.0},
        trace_id="trc_1",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        replica_record_id=replica.id,
        replica_version=replica.version,
        trace_id="trc_1",
    )

    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.REJECTED
    assert dto.rejections_count == 1
    assert len(setup_env.writer.upserted) == 0

    assert len(setup_env.dp_uow.normalization_rejections.rejections) == 1
    assert (
        setup_env.dp_uow.normalization_rejections.rejections[0].reason_code
        == NormalizationRejectionReason.QUALITY_RULE_REJECTED.value
    )
    trace_types = [t.event_type for t in setup_env.dp_uow.traces.events]
    assert IpTraceEventType.NORMALIZATION_REJECTED.value in trace_types


@pytest.mark.asyncio
async def test_normalize_tombstone_cascades_soft_delete(setup_env: NormalizationTestEnv) -> None:
    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
    )
    await setup_env.cp_uow.transformations.save(transformation)

    prev_ledger = NormalizationLedgerEntry.create(
        tenant_id="tenant_1",
        replica_record_id="rep_tomb",
        replica_version=1,
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
        produced_canonical_refs=(("canonical.record_alpha", "rec_tomb"),),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_prev",
    )
    await setup_env.dp_uow.normalization_ledger.record_entry(prev_ledger)

    replica = ReplicaRecord(
        id="rep_tomb",
        tenant_id="tenant_1",
        trace_id="trc_tomb",
        correlation_id=None,
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_tomb",
        primary_key_values=(),
        cursor_value=None,
        cursor_kind=None,
        data={},
        data_hash="hash_0",
        version=2,
        generation_id=1,
        last_seen_generation=1,
        first_seen_at=datetime.now(UTC),
        extracted_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=datetime.now(UTC),
        source_inbound_record_id="",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        replica_record_id="rep_tomb",
        replica_version=2,
        trace_id="trc_tomb",
    )

    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.TOMBSTONED

    assert "rec_tomb" in setup_env.writer.soft_deleted

    tomb_events = [
        e
        for e in setup_env.dp_uow.normalization_ledger.events
        if isinstance(e, CanonicalRecordChangedEvent)
        and e.action == CanonicalAction.TOMBSTONE.value
    ]
    assert len(tomb_events) == 1
    assert tomb_events[0].source_id == "rec_tomb"

    trace_types = [t.event_type for t in setup_env.dp_uow.traces.events]
    assert IpTraceEventType.TOMBSTONED.value in trace_types


@pytest.mark.asyncio
async def test_normalize_terminal_transformer_error_handling(
    setup_env: NormalizationTestEnv,
) -> None:
    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        transformation_id="synthetic.record_alpha",
        transformation_version=1,
    )
    await setup_env.cp_uow.transformations.save(transformation)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        record_key="rec_err",
        data={"trigger_error": True},
        trace_id="trc_err",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="records_alpha",
        replica_record_id=replica.id,
        replica_version=replica.version,
        trace_id="trc_err",
    )

    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.REJECTED
    assert dto.rejections_count == 1
    assert "Invalid field format" in str(dto.error_detail)
    assert setup_env.dp_uow.committed

    trace_types = [t.event_type for t in setup_env.dp_uow.traces.events]
    assert IpTraceEventType.NORMALIZATION_REJECTED.value in trace_types


@pytest.mark.asyncio
async def test_backfill_stream_normalization_chunks_records(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies BackfillStreamNormalizationUseCase processes stream replicas in bounded chunks."""
    await setup_env.cp_uow.transformations.save(
        Transformation.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            transformation_id="synthetic.record_alpha",
            transformation_version=1,
        )
    )

    for idx in range(5):
        rep = ReplicaRecord.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            record_key=f"rec_bf_{idx}",
            data={"metric_value": float(idx * 10), "serial": f"SN-BF-{idx}"},
            trace_id=f"trc_bf_{idx}",
        )
        await setup_env.dp_uow.replica_records.save(rep)

    backfill_uc = BackfillStreamNormalizationUseCase(
        data_plane_uow_provider=setup_env.dp_provider,
        normalize_use_case=setup_env.use_case,
    )
    result = await backfill_uc.execute(
        BackfillStreamNormalizationCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="records_alpha",
            chunk_size=2,
        )
    )
    assert result.is_ok
    summary = result.unwrap()
    assert summary.processed_count == 5
    assert summary.normalized_count == 5
    assert summary.chunks_processed == 3
    assert len(setup_env.writer.upserted) == 5
