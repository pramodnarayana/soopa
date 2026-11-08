"""Shared pure in-memory test fakes for trace query and stage replay use-case unit tests."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence

from ip.engine.application.responses import IpTraceLineageItemDTO
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.dispatch.quarantine_record import QuarantineRecord
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.domain.normalization.ledger import (
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap, NormalizedRecord
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.trace import IpTraceStatus as TraceStatus
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
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from seedwork.events import EventEnvelope
from strace.domain import TraceEvent
from strace.ports import TraceRepositoryPort


class InMemoryInboundRecordRepo(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def save_batch(self, records: Sequence[InboundRecord]) -> None:
        for record in records:
            self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

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
        target_ids = list(record_ids) or ([range_start] if range_start else [])
        return [
            self.records[rec_id]
            for rec_id in target_ids
            if rec_id in self.records and self.records[rec_id].tenant_id == tenant_id
        ]

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        _ = hydrate_payloads
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
        return None

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


class InMemoryReplicaRecordRepo(ReplicaRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, ReplicaRecord] = {}

    async def save(self, record: ReplicaRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, tenant_id: str, record_id: str) -> ReplicaRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_key(
        self, tenant_id: str, connection_id: str, stream: str, record_key: str
    ) -> ReplicaRecord | None:
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
        return []

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[ReplicaRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]


class InMemoryNormalizedRecordRepo(NormalizedRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, NormalizedRecord] = {}

    async def save(self, record: NormalizedRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def list_by_source(
        self, tenant_id: str, canonical_type: str, source_id: str
    ) -> Sequence[NormalizedRecord]:
        return []

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[NormalizedRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]


class InMemoryOutboundRecordRepo(OutboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, OutboundRecord] = {}

    async def save(self, record: OutboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> Sequence[OutboundRecord]:
        _ = hydrate_payloads
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]


class InMemoryTraceRepo(TraceRepositoryPort):
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.lineage_items: list[IpTraceLineageItemDTO] = []

    async def list_trace_events(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        return [e for e in self.events if e.tenant_id == tenant_id and e.trace_id == trace_id]

    async def save_trace_event(
        self,
        event: TraceEvent,
    ) -> None:
        self.events.append(event)

    async def save_all_trace_events(
        self,
        events: Sequence[TraceEvent],
    ) -> None:
        self.events.extend(events)

    async def resolve_root_trace_id(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> str:
        _ = tenant_id
        return trace_id

    async def get_trace_lineage(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[IpTraceLineageItemDTO]:
        _ = (tenant_id, trace_id)
        return list(self.lineage_items)

    async def find_traces_by_correlation_id(
        self,
        tenant_id: str,
        correlation_id: str,
        *,
        limit: int = 50,
    ) -> list[IpTraceLineageItemDTO]:
        _ = tenant_id
        return [item for item in self.lineage_items if item.correlation_id == correlation_id][
            :limit
        ]

    async def list_recent_traces(
        self,
        tenant_id: str,
        *,
        status: TraceStatus | str | None = None,
        min_replay_count: int | None = None,
        limit: int = 50,
    ) -> list[IpTraceLineageItemDTO]:
        _ = tenant_id
        target_status = status.value if isinstance(status, TraceStatus) else status
        matching = [
            item
            for item in self.lineage_items
            if (target_status is None or str(item.status) == target_status)
            and (min_replay_count is None or item.replay_count >= min_replay_count)
        ]
        ordered = sorted(
            matching,
            key=lambda item: str(item.created_at or ""),
            reverse=True,
        )
        return ordered[:limit]


class DummyReplicaRejectionRepo(ReplicaRejectionRepositoryPort):
    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        pass


class DummyEntityMapRepo(GlobalEntityMapRepositoryPort):
    async def save(self, entity_map: GlobalEntityMap) -> None:
        pass

    async def get_by_source(
        self,
        tenant_id: str,
        entity_domain: str,
        source_connection_id: str,
        source_entity_id: str,
    ) -> GlobalEntityMap | None:
        return None

    async def get_by_canonical_id(
        self, tenant_id: str, canonical_id: str
    ) -> Sequence[GlobalEntityMap]:
        return ()


class DummyLedgerRepo(NormalizationLedgerRepositoryPort):
    async def get_latest_version(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> int | None:
        return None

    async def get_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> tuple[tuple[str, str], ...]:
        return ()

    async def get_latest_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
    ) -> tuple[tuple[str, str], ...]:
        return ()

    async def record_entry(self, entry: NormalizationLedgerEntry) -> None:
        pass


class DummyNormRejectionRepo(NormalizationRejectionRepositoryPort):
    async def record_rejection(self, rejection: NormalizationRejectionEntry) -> None:
        pass

    async def record_shadow_diff(self, diff: NormalizationShadowDiffEntry) -> None:
        pass


class DummyPendingRefRepo(PendingReferenceRepositoryPort):
    async def record_pending(self, entry: PendingReferenceEntry) -> None:
        pass

    async def resolve_pending_for_target(
        self,
        *,
        tenant_id: str,
        source_connection_id: str,
        target_canonical_type: str,
        target_source_id: str,
    ) -> list[PendingReferenceEntry]:
        return []


class InMemoryQuarantineRecordRepo(QuarantineRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, QuarantineRecord] = {}

    async def save(self, record: QuarantineRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> QuarantineRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[QuarantineRecord]:
        items = [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and (connection_id is None or r.connection_id == connection_id)
        ]
        return items[offset : offset + limit]


class InMemoryDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.inbound_records = InMemoryInboundRecordRepo()
        self.replica_records = InMemoryReplicaRecordRepo()
        self.replica_rejections = DummyReplicaRejectionRepo()
        self.normalized_records = InMemoryNormalizedRecordRepo()
        self.entity_maps = DummyEntityMapRepo()
        self.outbound_records = InMemoryOutboundRecordRepo()
        self.quarantine_records = InMemoryQuarantineRecordRepo()
        self.normalization_ledger = DummyLedgerRepo()
        self.normalization_rejections = DummyNormRejectionRepo()
        self.pending_references = DummyPendingRefRepo()
        self.traces = InMemoryTraceRepo()
        self.committed = False

    async def __aenter__(self) -> InMemoryDataPlaneUoW:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        _ = (tenant_id, idempotency_key)
        return True

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        _ = (tenant_id, idempotency_key)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        _ = envelope


class InMemoryDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(
        self,
        uow: InMemoryDataPlaneUoW,
        *,
        missing_tenant_ids: set[str] | None = None,
    ) -> None:
        self._uow = uow
        self._missing_tenant_ids = missing_tenant_ids or set()

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        if tenant_id in self._missing_tenant_ids:
            return Result.err(TenantShardNotFoundError.for_tenant(tenant_id))
        return Result.ok(("shard_01", "postgresql+asyncpg://localhost/shard_01"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (tenant_id, shard_id, shard_dsn)
        yield self._uow
