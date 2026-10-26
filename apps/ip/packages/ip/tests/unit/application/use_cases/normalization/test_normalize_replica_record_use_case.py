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
from ip.engine.domain.enums import (
    CanonicalAction,
    IpTraceEventType,
    MappingMode,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
    RuleSeverity,
)
from ip.engine.domain.events import CanonicalRecordChangedEvent
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.normalization import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    MappingBinding,
    MappingContext,
    MappingRejection,
    MappingResult,
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
    ReplicaSnapshot,
    SourceReference,
)
from ip.engine.domain.services.canonical_entity_registry import CanonicalEntityRegistry
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.domain.services.default_normalization_error_policy import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.services.mapper_registry import InMemoryMapperRegistry
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.entity_map_repository_port import (
    GlobalEntityMapRepositoryPort,
)
from ip.engine.ports.outbound.inbound_record_repository_port import (
    InboundRecordRepositoryPort,
)
from ip.engine.ports.outbound.mapper_port import MapperPort
from ip.engine.ports.outbound.mapping_binding_repository_port import (
    MappingBindingRepositoryPort,
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
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
    ReplicaRecordRepositoryPort,
)
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.stream_state_repository_port import (
    StreamStateRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from seedwork.domain.types import JsonDict
from seedwork.events import DomainEvent
from strace.domain import TraceEvent

# ---------------------------------------------------------------------------
# In-Memory Test Fakes
# ---------------------------------------------------------------------------


class FakeMappingBindingRepository(MappingBindingRepositoryPort):
    def __init__(self) -> None:
        self.bindings: dict[tuple[str, str, str], MappingBinding] = {}

    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> MappingBinding | None:
        return self.bindings.get((tenant_id, connection_id, stream))

    async def save(self, binding: MappingBinding) -> None:
        self.bindings[(binding.tenant_id, binding.connection_id, binding.stream)] = binding

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> list[MappingBinding]:
        return [
            b
            for b in self.bindings.values()
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

    async def merge_batch(self, candidates: Sequence[ReplicaMergeCandidate]) -> list[MergeResult]:
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


class FakeNormalizationLedgerRepository(NormalizationLedgerRepositoryPort):
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str, int], NormalizationLedgerEntry] = {}

    async def get_latest_version(
        self, *, tenant_id: str, replica_record_id: str, mapping_id: str, mapping_version: int
    ) -> int | None:
        key = (tenant_id, replica_record_id, mapping_id, mapping_version)
        entry = self.entries.get(key)
        return entry.replica_version if entry else None

    async def get_produced_refs(
        self, *, tenant_id: str, replica_record_id: str, mapping_id: str, mapping_version: int
    ) -> tuple[tuple[str, str], ...]:
        key = (tenant_id, replica_record_id, mapping_id, mapping_version)
        entry = self.entries.get(key)
        return entry.produced_canonical_refs if entry else ()

    async def get_latest_produced_refs(
        self, *, tenant_id: str, replica_record_id: str, mapping_id: str
    ) -> tuple[tuple[str, str], ...]:
        matching = [
            e
            for e in self.entries.values()
            if e.tenant_id == tenant_id
            and e.replica_record_id == replica_record_id
            and e.mapping_id == mapping_id
            and e.outcome in (NormalizationOutcome.NORMALIZED, NormalizationOutcome.TOMBSTONED)
        ]
        if not matching:
            return ()
        matching.sort(key=lambda e: (e.created_at, e.replica_version), reverse=True)
        return matching[0].produced_canonical_refs

    async def record_entry(self, entry: NormalizationLedgerEntry) -> None:
        key = (entry.tenant_id, entry.replica_record_id, entry.mapping_id, entry.mapping_version)
        self.entries[key] = entry


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
    normalization_ledger: FakeNormalizationLedgerRepository
    normalization_rejections: FakeNormalizationRejectionRepository
    pending_references: FakePendingReferenceRepository

    def __init__(self) -> None:
        self.replica_records = FakeReplicaRecordRepository()
        self.normalization_ledger = FakeNormalizationLedgerRepository()
        self.normalization_rejections = FakeNormalizationRejectionRepository()
        self.pending_references = FakePendingReferenceRepository()
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def __aenter__(self) -> FakeDataPlaneUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


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
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    mapping_bindings: FakeMappingBindingRepository

    def __init__(self) -> None:
        self.mapping_bindings = FakeMappingBindingRepository()

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
        mapping_id: str,
        mapping_version: int,
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


class SimpleMapper(MapperPort):
    def __init__(self, m_id: str, m_ver: int, multiplier: float = 1.0) -> None:
        self._id = m_id
        self._ver = m_ver
        self._multiplier = multiplier

    @property
    def mapping_id(self) -> str:
        return self._id

    @property
    def mapping_version(self) -> int:
        return self._ver

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("energy.meter_reading",)

    def map(self, replica: ReplicaSnapshot, context: MappingContext) -> MappingResult:
        if replica.data.get("trigger_error"):
            raise ValueError("Invalid field format in payload")

        if replica.data.get("reject_flag"):
            return MappingResult(
                rejections=(
                    MappingRejection(
                        reason=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED,
                        field_path="serial",
                        detail="Serial is blacklisted",
                    ),
                )
            )

        raw_kwh = replica.data.get("kwh", 0.0)
        kwh_val = float(raw_kwh) * self._multiplier if isinstance(raw_kwh, (int, float)) else 0.0
        target_sp = str(replica.data.get("service_point_source_id", "sp_999"))
        draft = CanonicalDraft(
            canonical_type="energy.meter_reading",
            source_id=replica.record_key,
            fields={
                "kwh": kwh_val,
                "meter_serial": replica.data.get("serial"),
            },
            references=(
                SourceReference(
                    field_name="service_point_id",
                    target_canonical_type="energy.service_point",
                    target_source_id=target_sp,
                ),
            ),
        )
        return MappingResult(drafts=(draft,))


class ServicePointMapper(MapperPort):
    @property
    def mapping_id(self) -> str:
        return "energy.ami_service_point"

    @property
    def mapping_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("energy.service_point",)

    def map(self, replica: ReplicaSnapshot, context: MappingContext) -> MappingResult:
        draft = CanonicalDraft(
            canonical_type="energy.service_point",
            source_id=replica.record_key,
            fields={"utility_code": replica.data.get("utility_code", "ERCOT")},
        )
        return MappingResult(drafts=(draft,))


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
    sp_writer: RecordingCanonicalWriter
    mapper_registry: InMemoryMapperRegistry
    writer_registry: InMemoryCanonicalWriterRegistry[CanonicalWriterPort]
    entity_registry: CanonicalEntityRegistry


@pytest.fixture
def setup_env() -> NormalizationTestEnv:
    cp_uow = FakeControlPlaneUoW()
    dp_uow = FakeDataPlaneUoW()
    dp_provider = FakeDataPlaneUoWProvider(dp_uow)
    mapper_registry = InMemoryMapperRegistry()
    writer_registry: InMemoryCanonicalWriterRegistry[CanonicalWriterPort] = (
        InMemoryCanonicalWriterRegistry()
    )
    entity_registry = CanonicalEntityRegistry()
    error_policy = DefaultNormalizationErrorPolicy()

    mapper = SimpleMapper("energy.ami_meter_reading", 1)
    mapper_registry.register(mapper)
    mapper_registry.register(ServicePointMapper())

    writer = RecordingCanonicalWriter("energy.meter_reading")
    sp_writer = RecordingCanonicalWriter("energy.service_point")
    writer_registry.register(writer)
    writer_registry.register(sp_writer)

    use_case = NormalizeReplicaRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_provider,
        mapper_registry=mapper_registry,
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
        sp_writer=sp_writer,
        mapper_registry=mapper_registry,
        writer_registry=writer_registry,
        entity_registry=entity_registry,
    )


@pytest.mark.asyncio
async def test_normalize_skipped_no_binding(setup_env: NormalizationTestEnv) -> None:
    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        replica_record_id="rep_1",
        replica_version=1,
        trace_id="trc_1",
    )
    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    assert result.unwrap().outcome == NormalizationOutcome.SKIPPED_NO_BINDING


@pytest.mark.asyncio
async def test_normalize_version_guard_skips_stale_and_emits_trace(
    setup_env: NormalizationTestEnv,
) -> None:
    binding = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    await setup_env.cp_uow.mapping_bindings.save(binding)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_stale",
        data={"kwh": 10.0},
        trace_id="trc_old",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    ledger_entry = NormalizationLedgerEntry.create(
        tenant_id="tenant_1",
        replica_record_id=replica.id,
        replica_version=3,
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        produced_canonical_refs=(),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_old",
    )
    await setup_env.dp_uow.normalization_ledger.record_entry(ledger_entry)

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        replica_record_id=replica.id,
        replica_version=2,
        trace_id="trc_new",
    )
    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    assert result.unwrap().outcome == NormalizationOutcome.SKIPPED_STALE

    trace_types = [t.event_type for t in setup_env.dp_uow.replica_records.trace_events]
    assert IpTraceEventType.L3_SKIPPED_STALE.value in trace_types


@pytest.mark.asyncio
async def test_normalize_success_upserts_and_emits_event_and_trace(
    setup_env: NormalizationTestEnv,
) -> None:
    binding = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    await setup_env.cp_uow.mapping_bindings.save(binding)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_100",
        data={"kwh": 105.4, "serial": "SN-MTR-1"},
        trace_id="trc_1",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        replica_record_id=replica.id,
        replica_version=replica.version,
        trace_id="trc_1",
    )

    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.NORMALIZED
    assert dto.canonical_refs_produced == (("energy.meter_reading", "mtr_100"),)
    assert setup_env.dp_uow.committed

    assert len(setup_env.writer.upserted) == 1
    assert setup_env.writer.upserted[0][0] == "mtr_100"
    assert setup_env.writer.upserted[0][1]["kwh"] == 105.4

    assert len(setup_env.dp_uow.pending_references.pending) == 1
    pref = setup_env.dp_uow.pending_references.pending[0]
    assert pref.target_canonical_type == "energy.service_point"
    assert pref.target_source_id == "sp_999"

    events = [
        e
        for e in setup_env.dp_uow.replica_records.events
        if isinstance(e, CanonicalRecordChangedEvent)
    ]
    assert len(events) == 1
    assert events[0].action == CanonicalAction.UPSERT.value
    assert events[0].canonical_type == "energy.meter_reading"
    assert events[0].source_id == "mtr_100"

    trace_events = setup_env.dp_uow.replica_records.trace_events
    trace_types = [t.event_type for t in trace_events]
    assert IpTraceEventType.L3_REFERENCE_PENDING.value in trace_types
    assert IpTraceEventType.L3_NORMALIZED.value in trace_types
    normalized_trace = next(
        t for t in trace_events if t.event_type == IpTraceEventType.L3_NORMALIZED.value
    )
    assert normalized_trace.metadata is not None
    assert normalized_trace.metadata["mapping_id"] == "energy.ami_meter_reading"
    assert normalized_trace.metadata["mapping_version"] == 1


@pytest.mark.asyncio
async def test_normalize_reference_resolution_and_late_arrival_backpatching(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies Step 5 immediate reference resolution and Step 13 late-arriving back-patching."""
    await setup_env.cp_uow.mapping_bindings.save(
        MappingBinding.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="readings",
            mapping_id="energy.ami_meter_reading",
            mapping_version=1,
        )
    )
    await setup_env.cp_uow.mapping_bindings.save(
        MappingBinding.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="service_points",
            mapping_id="energy.ami_service_point",
            mapping_version=1,
        )
    )

    # 1. Reading arrives BEFORE service point sp_999 -> records pending reference
    reading_rep = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_early",
        data={"kwh": 42.0, "serial": "SN-1", "service_point_source_id": "sp_999"},
        trace_id="trc_early",
    )
    await setup_env.dp_uow.replica_records.save(reading_rep)
    res1 = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="readings",
            replica_record_id=reading_rep.id,
            replica_version=reading_rep.version,
            trace_id="trc_early",
        )
    )
    assert res1.is_ok
    assert "service_point_id" not in setup_env.writer.rows_by_source_id["mtr_early"]
    assert len(setup_env.dp_uow.pending_references.pending) == 1

    # 2. Service point sp_999 arrives later -> back-patches mtr_early's service_point_id!
    sp_rep = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="service_points",
        record_key="sp_999",
        data={"utility_code": "ONCOR"},
        trace_id="trc_sp",
    )
    await setup_env.dp_uow.replica_records.save(sp_rep)
    setup_env.dp_uow.replica_records.trace_events.clear()

    res2 = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="service_points",
            replica_record_id=sp_rep.id,
            replica_version=sp_rep.version,
            trace_id="trc_sp",
        )
    )
    assert res2.is_ok
    assert res2.unwrap().resolved_references_count == 1
    assert setup_env.writer.resolved_references == [
        ("mtr_early", "service_point_id", "canon_energy.service_point_sp_999")
    ]
    assert (
        setup_env.writer.rows_by_source_id["mtr_early"]["service_point_id"]
        == "canon_energy.service_point_sp_999"
    )
    trace_types = [t.event_type for t in setup_env.dp_uow.replica_records.trace_events]
    assert IpTraceEventType.L3_REFERENCE_RESOLVED.value in trace_types

    # 3. Second reading referencing existing sp_999 resolves immediately without pending reference!
    reading_rep2 = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_after_sp",
        data={"kwh": 88.0, "serial": "SN-2", "service_point_source_id": "sp_999"},
        trace_id="trc_after",
    )
    await setup_env.dp_uow.replica_records.save(reading_rep2)
    res3 = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="readings",
            replica_record_id=reading_rep2.id,
            replica_version=reading_rep2.version,
            trace_id="trc_after",
        )
    )
    assert res3.is_ok
    assert (
        setup_env.writer.rows_by_source_id["mtr_after_sp"]["service_point_id"]
        == "canon_energy.service_point_sp_999"
    )
    # Still only 1 pending reference entry in total (which is RESOLVED)
    assert len(setup_env.dp_uow.pending_references.pending) == 1


@pytest.mark.asyncio
async def test_normalize_shadow_mode_does_not_mutate_canonical_or_outbox(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies MappingMode.SHADOW writes only shadow diffs and never mutates canonical tables or outbox."""
    # Register v2 mapper with 2.0 multiplier
    setup_env.mapper_registry.register(SimpleMapper("energy.ami_meter_reading", 2, multiplier=2.0))

    binding = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        mode=MappingMode.SHADOW,
        shadow_mapping_version=2,
    )
    await setup_env.cp_uow.mapping_bindings.save(binding)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_shadow",
        data={"kwh": 50.0, "serial": "SN-SHD"},
        trace_id="trc_shd",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.events.clear()
    setup_env.dp_uow.replica_records.trace_events.clear()

    result = await setup_env.use_case.execute(
        NormalizeReplicaRecordCommand(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="readings",
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
    assert len(setup_env.dp_uow.replica_records.events) == 0
    # Shadow diff MUST be recorded
    assert len(setup_env.dp_uow.normalization_rejections.shadow_diffs) == 1
    diff_entry = setup_env.dp_uow.normalization_rejections.shadow_diffs[0]
    assert diff_entry.candidate_version == 2
    assert diff_entry.diff_data == {
        "energy.meter_reading:mtr_shadow": {
            "kwh": {"active": 50.0, "shadow": 100.0},
        }
    }


@pytest.mark.asyncio
async def test_normalize_quality_rule_rejection(setup_env: NormalizationTestEnv) -> None:
    rule = MockQualityRule("REQ_SERIAL", RuleSeverity.REJECT, "meter_serial")
    setup_env.entity_registry.register(
        CanonicalEntityDefinition(
            canonical_type="energy.meter_reading",
            schema_version=1,
            quality_rules=(rule,),
        )
    )

    binding = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    await setup_env.cp_uow.mapping_bindings.save(binding)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_invalid",
        data={"kwh": 50.0},
        trace_id="trc_1",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
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
    trace_types = [t.event_type for t in setup_env.dp_uow.replica_records.trace_events]
    assert IpTraceEventType.L3_REJECTED.value in trace_types


@pytest.mark.asyncio
async def test_normalize_tombstone_cascades_soft_delete(setup_env: NormalizationTestEnv) -> None:
    binding = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    await setup_env.cp_uow.mapping_bindings.save(binding)

    prev_ledger = NormalizationLedgerEntry.create(
        tenant_id="tenant_1",
        replica_record_id="rep_tomb",
        replica_version=1,
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        produced_canonical_refs=(("energy.meter_reading", "mtr_tomb"),),
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
        stream="readings",
        record_key="mtr_tomb",
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
        stream="readings",
        replica_record_id="rep_tomb",
        replica_version=2,
        trace_id="trc_tomb",
    )

    result = await setup_env.use_case.execute(command)
    assert result.is_ok
    dto = result.unwrap()
    assert dto.outcome == NormalizationOutcome.TOMBSTONED

    assert "mtr_tomb" in setup_env.writer.soft_deleted

    tomb_events = [
        e
        for e in setup_env.dp_uow.replica_records.events
        if isinstance(e, CanonicalRecordChangedEvent)
        and e.action == CanonicalAction.TOMBSTONE.value
    ]
    assert len(tomb_events) == 1
    assert tomb_events[0].source_id == "mtr_tomb"

    trace_types = [t.event_type for t in setup_env.dp_uow.replica_records.trace_events]
    assert IpTraceEventType.L3_TOMBSTONED.value in trace_types


@pytest.mark.asyncio
async def test_normalize_terminal_mapper_error_handling(setup_env: NormalizationTestEnv) -> None:
    binding = MappingBinding.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    await setup_env.cp_uow.mapping_bindings.save(binding)

    replica = ReplicaRecord.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        record_key="mtr_err",
        data={"trigger_error": True},
        trace_id="trc_err",
    )
    await setup_env.dp_uow.replica_records.save(replica)
    setup_env.dp_uow.replica_records.trace_events.clear()

    command = NormalizeReplicaRecordCommand(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
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

    trace_types = [t.event_type for t in setup_env.dp_uow.replica_records.trace_events]
    assert IpTraceEventType.L3_REJECTED.value in trace_types


@pytest.mark.asyncio
async def test_backfill_stream_normalization_chunks_records(
    setup_env: NormalizationTestEnv,
) -> None:
    """Verifies BackfillStreamNormalizationUseCase processes stream replicas in bounded chunks."""
    await setup_env.cp_uow.mapping_bindings.save(
        MappingBinding.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="readings",
            mapping_id="energy.ami_meter_reading",
            mapping_version=1,
        )
    )

    for idx in range(5):
        rep = ReplicaRecord.create(
            tenant_id="tenant_1",
            connection_id="conn_1",
            stream="readings",
            record_key=f"mtr_bf_{idx}",
            data={"kwh": float(idx * 10), "serial": f"SN-BF-{idx}"},
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
            stream="readings",
            chunk_size=2,
        )
    )
    assert result.is_ok
    summary = result.unwrap()
    assert summary.processed_count == 5
    assert summary.normalized_count == 5
    assert summary.chunks_processed == 3
    assert len(setup_env.writer.upserted) == 5
