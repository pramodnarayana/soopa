"""Application use-case unit tests for GetIpTrace, GetIpTraceLineage, ReplayTransaction, ModifyAndReplay, and BulkReplay."""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from ip.engine.application.dtos.trace import IpTraceLineageItemDTO
from ip.engine.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayCommand,
    BulkReplayTransactionsUseCase,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_lineage_use_case import (
    GetIpTraceLineageQuery,
    GetIpTraceLineageUseCase,
    ListRecentTracesQuery,
    SearchTracesByCorrelationQuery,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_use_case import (
    GetIpTraceQuery,
    GetIpTraceUseCase,
)
from ip.engine.application.use_cases.transactions.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayTransactionUseCase,
)
from ip.engine.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionCommand,
    ReplayTransactionUseCase,
)
from ip.engine.domain.enums import (
    HttpWriteOperation,
    IngestionMode,
    PipelineLayer,
    ReplayStage,
)
from ip.engine.domain.exceptions import (
    IpErrorCode,
    Result,
    TenantShardNotFoundError,
)
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.normalization import (
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
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
from strace.domain import TraceEvent, TraceStatus
from strace.ports import TraceRepositoryPort


class InMemoryInboundRecordRepo(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

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
        status: TraceStatus | None = None,
        min_replay_count: int | None = None,
        limit: int = 50,
    ) -> list[IpTraceLineageItemDTO]:
        _ = tenant_id
        matching = [
            item
            for item in self.lineage_items
            if (status is None or str(item.status) == status.value)
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


class InMemoryDataPlaneUoW(IpDataPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.inbound_records = InMemoryInboundRecordRepo()
        self.replica_records = InMemoryReplicaRecordRepo()
        self.replica_rejections = DummyReplicaRejectionRepo()
        self.normalized_records = InMemoryNormalizedRecordRepo()
        self.entity_maps = DummyEntityMapRepo()
        self.outbound_records = InMemoryOutboundRecordRepo()
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
    def __init__(self, uow: InMemoryDataPlaneUoW) -> None:
        self._uow = uow

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        _ = tenant_id
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


@pytest.mark.asyncio
async def test_get_ip_trace_use_case_returns_waterfall_or_not_found() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    use_case = GetIpTraceUseCase(uow_provider=provider)

    missing_res = await use_case.execute(
        GetIpTraceQuery(tenant_id="ten_01", trace_id="ip_trc_missing")
    )
    assert missing_res.is_err
    assert missing_res.unwrap_err().code == IpErrorCode.TRACE_NOT_FOUND

    inb = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="itron_mdm",
        stream_name="meter_reads",
        payload_bytes=b'{"meter_id":"MTR-100"}',
        is_inlined=True,
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        ingestion_mode=IngestionMode.PUSH_FULL,
        request_body={"meter_id": "MTR-100"},
    )
    await uow.inbound_records.save(inb)

    ok_res = await use_case.execute(GetIpTraceQuery(tenant_id="ten_01", trace_id="ip_trc_01"))
    assert ok_res.is_ok
    trace_dto = ok_res.unwrap()
    assert trace_dto.trace_id == "ip_trc_01"
    assert trace_dto.correlation_id == "MTR-100"
    assert trace_dto.inbound_record is not None
    assert trace_dto.inbound_record.id == inb.id


@pytest.mark.asyncio
async def test_get_ip_trace_lineage_and_correlation_search() -> None:
    uow = InMemoryDataPlaneUoW()
    now = datetime.now(UTC)
    uow.traces.lineage_items = [
        IpTraceLineageItemDTO(
            trace_id="ip_trc_root",
            correlation_id="MTR-100",
            status=TraceStatus.FAILED,
            primary_layer=PipelineLayer.L5_DELIVER.value,
            created_at=now,
            replay_count=0,
            original_trace_id="ip_trc_root",
        ),
        IpTraceLineageItemDTO(
            trace_id="ip_trc_replay_1",
            correlation_id="MTR-100",
            status=TraceStatus.DELIVERED,
            primary_layer=PipelineLayer.L5_DELIVER.value,
            created_at=now,
            replay_count=1,
            parent_trace_id="ip_trc_root",
            original_trace_id="ip_trc_root",
        ),
    ]
    provider = InMemoryDataPlaneUoWProvider(uow)
    use_case = GetIpTraceLineageUseCase(uow_provider=provider)

    lineage_res = await use_case.execute(
        GetIpTraceLineageQuery(tenant_id="ten_01", trace_id="ip_trc_replay_1")
    )
    assert lineage_res.is_ok
    assert len(lineage_res.unwrap()) == 2

    corr_res = await use_case.search_by_correlation_id(
        SearchTracesByCorrelationQuery(tenant_id="ten_01", correlation_id="MTR-100")
    )
    assert corr_res.is_ok
    assert len(corr_res.unwrap()) == 2


@pytest.mark.asyncio
async def test_replay_transaction_use_case_across_all_stages_and_upstream_hydration() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    replay_uc = ReplayTransactionUseCase(uow_provider=provider)

    inb = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="itron_mdm",
        stream_name="meter_reads",
        payload_bytes=b'{"meter_id":"MTR-100","kwh":42.5}',
        is_inlined=True,
        trace_id="ip_trc_root",
        correlation_id="MTR-100",
        request_body={"meter_id": "MTR-100", "kwh": 42.5},
    )
    rep = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meter_reads",
        primary_key_values=("MTR-100",),
        data={"meter_id": "MTR-100", "kwh": 42.5},
        trace_id="ip_trc_root",
        correlation_id="MTR-100",
    )
    nrm = NormalizedRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        canonical_type="mdm.meter_reading",
        source_id="MTR-100",
        canonical_data={"meter_id": "MTR-100", "reading_kwh": 42.5},
        trace_id="ip_trc_root",
        correlation_id="MTR-100",
    )
    out = OutboundRecord.create_pending(
        tenant_id="ten_01",
        connection_id="conn_dest_01",
        app_id="netsuite_erp",
        stream_name="invoices",
        target_url="https://api.netsuite.example.com/v1/invoices",
        http_method="POST",
        payload_bytes=b'{"meter_id":"MTR-100"}',
        is_inlined=True,
        trace_id="ip_trc_root",
        operation=HttpWriteOperation.CREATE.value,
        correlation_id="MTR-100",
        request_body={"meter_id": "MTR-100"},
    )
    out.mark_failed(error_message="HTTP 503 Unavailable", response_status_code=503)

    await uow.inbound_records.save(inb)
    await uow.replica_records.save(rep)
    await uow.normalized_records.save(nrm)
    await uow.outbound_records.save(out)

    # 1. Replay L5 Delivery (RETRY_DELIVER)
    deliv_res = await replay_uc.execute(
        ReplayTransactionCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=ReplayStage.RETRY_DELIVER,
            actor="ops@soopa.io",
        )
    )
    assert deliv_res.is_ok
    deliv_dto = deliv_res.unwrap()
    assert deliv_dto.original_trace_id == "ip_trc_root"
    assert deliv_dto.parent_trace_id == "ip_trc_root"
    assert deliv_dto.replay_count == 1
    assert deliv_dto.stage == ReplayStage.RETRY_DELIVER

    # 2. Replay L3 Stitch from the L5 replay child trace (walks parent_trace_id upstream to find NormalizedRecord!)
    stitch_res = await replay_uc.execute(
        ReplayTransactionCommand(
            tenant_id="ten_01",
            trace_id=deliv_dto.new_trace_id,
            stage=ReplayStage.RETRY_STITCH,
            actor="ops@soopa.io",
        )
    )
    assert stitch_res.is_ok
    stitch_dto = stitch_res.unwrap()
    assert stitch_dto.original_trace_id == "ip_trc_root"
    assert stitch_dto.parent_trace_id == deliv_dto.new_trace_id
    assert stitch_dto.replay_count == 2

    # 3. Replay L1 Ingest
    ingest_res = await replay_uc.execute(
        ReplayTransactionCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=ReplayStage.RETRY_INGEST,
            actor="ops@soopa.io",
        )
    )
    assert ingest_res.is_ok
    assert ingest_res.unwrap().stage == ReplayStage.RETRY_INGEST

    # 4. Replay L2 Normalize
    norm_res = await replay_uc.execute(
        ReplayTransactionCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=ReplayStage.RETRY_NORMALIZE,
            actor="ops@soopa.io",
        )
    )
    assert norm_res.is_ok
    assert norm_res.unwrap().stage == ReplayStage.RETRY_NORMALIZE


@pytest.mark.asyncio
async def test_modify_and_replay_and_bulk_replay_use_cases() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    modify_uc = ModifyAndReplayTransactionUseCase(uow_provider=provider)
    bulk_uc = BulkReplayTransactionsUseCase(uow_provider=provider)

    inb1 = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="itron_mdm",
        stream_name="meter_reads",
        payload_bytes=b'{"meter_id":"MTR-101","kwh":10.0}',
        is_inlined=True,
        trace_id="ip_trc_m1",
        correlation_id="MTR-101",
        request_body={"meter_id": "MTR-101", "kwh": 10.0},
    )
    inb2 = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="itron_mdm",
        stream_name="meter_reads",
        payload_bytes=b'{"meter_id":"MTR-102","kwh":20.0}',
        is_inlined=True,
        trace_id="ip_trc_m2",
        correlation_id="MTR-102",
        request_body={"meter_id": "MTR-102", "kwh": 20.0},
    )
    await uow.inbound_records.save(inb1)
    await uow.inbound_records.save(inb2)

    bad_mod = await modify_uc.execute(
        ModifyAndReplayCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_m1",
            stage=ReplayStage.RETRY_INGEST,
            modified_payload={},
            actor="support@soopa.io",
        )
    )
    assert bad_mod.is_err
    assert bad_mod.unwrap_err().code == IpErrorCode.INVALID_REPLAY_PAYLOAD

    good_mod = await modify_uc.execute(
        ModifyAndReplayCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_m1",
            stage=ReplayStage.RETRY_INGEST,
            modified_payload={"meter_id": "MTR-101", "kwh": 99.9},
            actor="support@soopa.io",
        )
    )
    assert good_mod.is_ok
    mod_dto = good_mod.unwrap()
    replayed_inb = await uow.inbound_records.get_by_trace_id(mod_dto.new_trace_id, "ten_01")
    assert len(replayed_inb) == 1
    assert replayed_inb[0].request_body == {"meter_id": "MTR-101", "kwh": 99.9}

    bulk_res = await bulk_uc.execute(
        BulkReplayCommand(
            tenant_id="ten_01",
            trace_ids=("ip_trc_m1", "ip_trc_m1", "ip_trc_m2", "ip_trc_nonexistent"),
            stage=ReplayStage.RETRY_INGEST,
            actor="ops@soopa.io",
        )
    )
    assert bulk_res.is_ok
    bulk_dto = bulk_res.unwrap()
    assert bulk_dto.replayed_count == 2
    assert bulk_dto.succeeded_trace_ids == ("ip_trc_m1", "ip_trc_m2")
    assert len(bulk_dto.new_trace_ids) == 2
    assert len(bulk_dto.failed_items) == 1
    assert bulk_dto.failed_items[0].trace_id == "ip_trc_nonexistent"


@pytest.mark.asyncio
async def test_list_recent_traces_filters_and_orders_descending() -> None:
    uow = InMemoryDataPlaneUoW()
    tenant_id = f"ten_{os.urandom(12).hex()}"
    missing_tenant_id = f"ten_{os.urandom(12).hex()}"
    missing_trace_id = f"ip_trc_{os.urandom(12).hex()}"
    root_trace_id = f"ip_trc_{os.urandom(12).hex()}"
    failed_replay_trace_id = f"ip_trc_{os.urandom(12).hex()}"
    base_time = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)

    newer_delivered = [
        IpTraceLineageItemDTO(
            trace_id=f"ip_trc_{os.urandom(12).hex()}",
            correlation_id=f"MTR-{2000 + idx}",
            status=TraceStatus.DELIVERED,
            primary_layer=PipelineLayer.L5_DELIVER,
            created_at=base_time + timedelta(minutes=idx + 10),
            replay_count=0,
            parent_trace_id=None,
            original_trace_id=None,
        )
        for idx in range(320)
    ]
    uow.traces.lineage_items = [
        IpTraceLineageItemDTO(
            trace_id=failed_replay_trace_id,
            correlation_id="MTR-102",
            status=TraceStatus.FAILED,
            primary_layer=PipelineLayer.L5_DELIVER,
            created_at=base_time,
            replay_count=2,
            parent_trace_id=root_trace_id,
            original_trace_id=root_trace_id,
        ),
        *newer_delivered,
    ]

    class _Provider(IpDataPlaneUnitOfWorkProviderPort):
        async def resolve_shard_info(
            self, tenant_id: str
        ) -> Result[tuple[str, str], TenantShardNotFoundError]:
            _ = tenant_id
            return Result.ok(("shard-01", "postgresql+asyncpg://localhost/shard01"))

        @contextlib.asynccontextmanager
        async def get_data_plane_uow(
            self,
            tenant_id: str,
            shard_id: str,
            shard_dsn: str,
        ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
            _ = (tenant_id, shard_id, shard_dsn)
            yield uow

    lineage_uc = GetIpTraceLineageUseCase(uow_provider=_Provider())
    all_res = await lineage_uc.list_recent(ListRecentTracesQuery(tenant_id=tenant_id, limit=3))
    assert all_res.is_ok
    assert [item.trace_id for item in all_res.unwrap()] == [
        newer_delivered[-1].trace_id,
        newer_delivered[-2].trace_id,
        newer_delivered[-3].trace_id,
    ]

    filtered_res = await lineage_uc.list_recent(
        ListRecentTracesQuery(
            tenant_id=tenant_id,
            status=TraceStatus.FAILED,
            min_replay_count=1,
            limit=10,
        )
    )
    assert filtered_res.is_ok
    assert [item.trace_id for item in filtered_res.unwrap()] == [failed_replay_trace_id]

    class _MissingShardProvider(IpDataPlaneUnitOfWorkProviderPort):
        async def resolve_shard_info(
            self, tenant_id: str
        ) -> Result[tuple[str, str], TenantShardNotFoundError]:
            return Result.err(TenantShardNotFoundError.for_tenant(tenant_id))

        @contextlib.asynccontextmanager
        async def get_data_plane_uow(
            self,
            tenant_id: str,
            shard_id: str,
            shard_dsn: str,
        ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
            _ = (tenant_id, shard_id, shard_dsn)
            yield uow

    missing_uc = GetIpTraceLineageUseCase(uow_provider=_MissingShardProvider())
    assert (
        await missing_uc.execute(
            GetIpTraceLineageQuery(tenant_id=missing_tenant_id, trace_id=missing_trace_id)
        )
    ).is_err
    assert (
        await missing_uc.search_by_correlation_id(
            SearchTracesByCorrelationQuery(tenant_id=missing_tenant_id, correlation_id="MTR-1")
        )
    ).is_err
    assert (
        await missing_uc.list_recent(ListRecentTracesQuery(tenant_id=missing_tenant_id))
    ).is_err

