"""Unit tests for ReplicateRecordsUseCase and SweepStaleReplicasUseCase using pure in-memory test fakes."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicateRecordsCommand,
    ReplicateRecordsUseCase,
)
from ip.engine.application.use_cases.replication.sweep_stale_replicas_use_case import (
    SweepStaleReplicasCommand,
    SweepStaleReplicasUseCase,
)
from ip.engine.domain.enums import (
    CursorKind,
    MergeOutcome,
)
from ip.engine.domain.exceptions import PayloadNotFoundError
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import (
    ReplicaMergePolicy,
    ReplicaRecord,
    ReplicaRejection,
    compute_record_key,
)
from ip.engine.domain.models.stream_definition import (
    DeletionMarker,
    StreamDefinition,
)
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
    ReplicaRecordRepositoryPort,
)
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort


class FakeReplicaRecordRepository(ReplicaRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], ReplicaRecord] = {}
        self.batch_sizes: list[int] = []
        self.sweep_counts_queue: list[int] = []

    async def save(self, record: ReplicaRecord) -> None:
        key = (record.tenant_id, record.connection_id, record.stream, record.record_key)
        self.records[key] = record

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        return self.records.get((tenant_id, connection_id, stream, record_key))

    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
    ) -> list[MergeResult]:
        self.batch_sizes.append(len(candidates))
        results: list[MergeResult] = []
        for c in candidates:
            key = (c.tenant_id, c.connection_id, c.stream, c.record_key)
            existing = self.records.get(key)
            cursor_kind = (
                CursorKind(c.cursor_kind)
                if c.cursor_kind in CursorKind.__members__.values()
                else CursorKind.STRING
            )
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
                    data=c.data,
                    trace_id=c.trace_id,
                    primary_key_values=c.primary_key_values,
                    cursor_value=c.cursor_value,
                    cursor_kind=c.cursor_kind,
                    generation_id=c.generation_id,
                    source_inbound_record_id=c.source_inbound_record_id,
                )
                self.records[key] = rec
                results.append(
                    MergeResult(
                        record_id=rec.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=MergeOutcome.INSERT,
                        version=1,
                        data_hash=c.data_hash,
                    )
                )
            elif outcome == MergeOutcome.UPDATE:
                assert existing is not None
                existing.update_snapshot(
                    new_data=c.data,
                    trace_id=c.trace_id,
                    cursor_value=c.cursor_value,
                    generation_id=c.generation_id,
                    source_inbound_record_id=c.source_inbound_record_id,
                )
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=MergeOutcome.UPDATE,
                        version=existing.version,
                        data_hash=c.data_hash,
                    )
                )
            elif outcome == MergeOutcome.NOOP:
                assert existing is not None
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=MergeOutcome.NOOP,
                        version=existing.version,
                        data_hash=existing.data_hash,
                    )
                )
            elif outcome == MergeOutcome.STALE:
                assert existing is not None
                results.append(
                    MergeResult(
                        record_id=existing.id,
                        stream=c.stream,
                        record_key=c.record_key,
                        outcome=MergeOutcome.STALE,
                        version=existing.version,
                        data_hash=existing.data_hash,
                    )
                )
            elif outcome == MergeOutcome.TOMBSTONE:
                if existing is None:
                    rec = ReplicaRecord.create_tombstone(
                        tenant_id=c.tenant_id,
                        connection_id=c.connection_id,
                        stream=c.stream,
                        record_key=c.record_key,
                        data=c.data,
                        trace_id=c.trace_id,
                        primary_key_values=c.primary_key_values,
                        cursor_value=c.cursor_value,
                        cursor_kind=c.cursor_kind,
                        generation_id=c.generation_id,
                        source_inbound_record_id=c.source_inbound_record_id,
                    )
                    self.records[key] = rec
                    results.append(
                        MergeResult(
                            record_id=rec.id,
                            stream=c.stream,
                            record_key=c.record_key,
                            outcome=MergeOutcome.TOMBSTONE,
                            version=rec.version,
                            data_hash=rec.data_hash,
                        )
                    )
                else:
                    existing.tombstone(
                        trace_id=c.trace_id,
                        generation_id=c.generation_id,
                        source_inbound_record_id=c.source_inbound_record_id,
                    )
                    results.append(
                        MergeResult(
                            record_id=existing.id,
                            stream=c.stream,
                            record_key=c.record_key,
                            outcome=MergeOutcome.TOMBSTONE,
                            version=existing.version,
                            data_hash=existing.data_hash,
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
        if self.sweep_counts_queue:
            return self.sweep_counts_queue.pop(0)
        return 0


class FakeReplicaRejectionRepository(ReplicaRejectionRepositoryPort):
    def __init__(self) -> None:
        self.saved_rejections: list[ReplicaRejection] = []

    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        self.saved_rejections.extend(rejections)


class FakeInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[(record.tenant_id, record.id)] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        return self.records.get((tenant_id, record_id))

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[InboundRecord]:
        return [
            r for r in self.records.values() if r.tenant_id == tenant_id and r.trace_id == trace_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
        for r in self.records.values():
            if (
                r.tenant_id == tenant_id
                and r.connection_id == connection_id
                and r.external_event_id == external_event_id
            ):
                return r
        return None


class FakeNormalizedRecordRepository(NormalizedRecordRepositoryPort):
    async def save(self, record: NormalizedRecord) -> None:
        pass

    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        return None

    async def list_by_source(
        self, tenant_id: str, canonical_type: str, source_id: str
    ) -> Sequence[NormalizedRecord]:
        return ()


class FakeGlobalEntityMapRepository(GlobalEntityMapRepositoryPort):
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


class FakeOutboundRecordRepository(OutboundRecordRepositoryPort):
    async def save(self, record: OutboundRecord) -> None:
        pass

    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        return None

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[OutboundRecord]:
        return ()


class FakeDataPlaneUnitOfWork(IpDataPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.replica_records = FakeReplicaRecordRepository()
        self.replica_rejections = FakeReplicaRejectionRepository()
        self.inbound_records = FakeInboundRecordRepository()
        self.normalized_records = FakeNormalizedRecordRepository()
        self.entity_maps = FakeGlobalEntityMapRepository()
        self.outbound_records = FakeOutboundRecordRepository()
        self.committed = False
        self.commit_count = 0

    async def __aenter__(self) -> FakeDataPlaneUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


@pytest.mark.asyncio
async def test_replicate_records_inserts_and_updates() -> None:
    uow = FakeDataPlaneUnitOfWork()
    use_case = ReplicateRecordsUseCase(uow=uow)

    stream_def = StreamDefinition(
        stream="meters",
        primary_key=(("id",),),
        cursor_field=("updated_seq",),
        cursor_kind=CursorKind.INTEGER,
    )

    # 1. Initial batch -> 2 INSERTs
    cmd1 = ReplicateRecordsCommand(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        inbound_record_id="inb_01",
        generation_id=1,
        sync_id="sync_01",
        trace_id="trc_01",
        stream_definition=stream_def,
        raw_payload=[
            {"id": "m1", "val": 10, "updated_seq": 1},
            {"id": "m2", "val": 20, "updated_seq": 1},
        ],
    )

    res1 = await use_case.execute(cmd1)
    assert res1.is_ok
    summary1 = res1.value
    assert summary1.inserted_count == 2
    assert summary1.updated_count == 0
    assert summary1.noop_count == 0
    assert summary1.rejected_count == 0

    # 2. Second batch -> 1 UPDATE (m1 changed), 1 NOOP (m2 unchanged)
    cmd2 = ReplicateRecordsCommand(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        inbound_record_id="inb_02",
        generation_id=1,
        sync_id="sync_02",
        trace_id="trc_02",
        stream_definition=stream_def,
        raw_payload=[
            {"id": "m1", "val": 99, "updated_seq": 2},  # Changed
            {"id": "m2", "val": 20, "updated_seq": 1},  # Unchanged
        ],
    )

    res2 = await use_case.execute(cmd2)
    assert res2.is_ok
    summary2 = res2.value
    assert summary2.inserted_count == 0
    assert summary2.updated_count == 1
    assert summary2.noop_count == 1


@pytest.mark.asyncio
async def test_replicate_records_persists_rejections_with_registered_prefix() -> None:
    uow = FakeDataPlaneUnitOfWork()
    use_case = ReplicateRecordsUseCase(uow=uow)

    stream_def = StreamDefinition(
        stream="meters",
        primary_key=(("meter_code",),),
    )

    cmd = ReplicateRecordsCommand(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        inbound_record_id="inb_01",
        generation_id=1,
        sync_id="sync_01",
        trace_id="trc_01",
        stream_definition=stream_def,
        raw_payload=[
            {"meter_code": "M-100", "kwh": 50},
            {"kwh": 60},  # Missing meter_code -> rejection
        ],
    )

    res = await use_case.execute(cmd)
    assert res.is_ok
    summary = res.value
    assert summary.inserted_count == 1
    assert summary.rejected_count == 1
    assert len(uow.replica_rejections.saved_rejections) == 1
    rej = uow.replica_rejections.saved_rejections[0]
    assert rej.id.startswith("ip_rej_")
    assert rej.record_index == 1
    assert rej.reason == "MISSING_PRIMARY_KEY"


@pytest.mark.asyncio
async def test_replicate_records_unseen_delete_creates_tombstone() -> None:
    uow = FakeDataPlaneUnitOfWork()
    use_case = ReplicateRecordsUseCase(uow=uow)

    stream_def = StreamDefinition(
        stream="meters",
        primary_key=(("id",),),
        deletion_marker=DeletionMarker(field_path=("is_deleted",), expected_value=True),
    )

    cmd = ReplicateRecordsCommand(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        inbound_record_id="inb_del_01",
        generation_id=1,
        sync_id="sync_01",
        trace_id="trc_del_01",
        stream_definition=stream_def,
        raw_payload=[
            {"id": "m_unseen", "is_deleted": True},
        ],
    )

    res = await use_case.execute(cmd)
    assert res.is_ok
    summary = res.value
    assert summary.tombstone_count == 1
    assert summary.inserted_count == 0
    rec = await uow.replica_records.get_by_key(
        "ten_01", "conn_01", "meters", compute_record_key(("m_unseen",))
    )
    assert rec is not None
    assert rec.deleted_at is not None


@pytest.mark.asyncio
async def test_replicate_records_chunks_large_batches_by_500() -> None:
    uow = FakeDataPlaneUnitOfWork()
    use_case = ReplicateRecordsUseCase(uow=uow)

    stream_def = StreamDefinition(
        stream="meters",
        primary_key=(("id",),),
    )

    cmd = ReplicateRecordsCommand(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        inbound_record_id="inb_bulk_01",
        generation_id=1,
        sync_id="sync_bulk_01",
        trace_id="trc_bulk_01",
        stream_definition=stream_def,
        raw_payload=[{"id": f"m_{i}", "val": i} for i in range(525)],
    )

    res = await use_case.execute(cmd)
    assert res.is_ok
    summary = res.value
    assert summary.inserted_count == 525
    assert uow.replica_records.batch_sizes == [500, 25]


@pytest.mark.asyncio
async def test_replicate_records_missing_inbound_record_fails() -> None:
    uow = FakeDataPlaneUnitOfWork()
    use_case = ReplicateRecordsUseCase(uow=uow)
    cmd = ReplicateRecordsCommand(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream="users",
        inbound_record_id="rec_missing",
        generation_id=1,
        sync_id="sync_1",
        trace_id="trc_1",
    )
    result = await use_case.execute(cmd)
    assert result.is_err is True
    assert isinstance(result.error, PayloadNotFoundError)
    assert uow.committed is False


@pytest.mark.asyncio
async def test_replicate_records_from_wrapped_scalar_json_array() -> None:
    uow = FakeDataPlaneUnitOfWork()

    stream_def = StreamDefinition(
        stream="shipments",
        record_path=(),
        primary_key=(("id",),),
    )

    # Inbound record with wrapped scalar list and internal base64 key
    inbound = InboundRecord.create(
        tenant_id="ten_arr",
        connection_id="conn_arr",
        app_id="app_shipments",
        stream_name="shipments",
        payload_bytes=b'[{"id":"s1","status":"NEW"},{"id":"s2","status":"DONE"}]',
        is_inlined=True,
        request_body={
            "__wrapped_scalar__": [{"id": "s1", "status": "NEW"}, {"id": "s2", "status": "DONE"}],
            "__raw_payload_b64__": "W3siaWQiOiJzMSJ9XQ==",
        },
    )
    await uow.inbound_records.save(inbound)

    use_case = ReplicateRecordsUseCase(uow=uow)
    cmd = ReplicateRecordsCommand(
        tenant_id="ten_arr",
        connection_id="conn_arr",
        stream="shipments",
        inbound_record_id=inbound.id,
        generation_id=1,
        sync_id="sync_arr_1",
        trace_id="trc_arr_1",
        stream_definition=stream_def,
    )

    res = await use_case.execute(cmd)
    assert res.is_ok is True
    summary = res.value
    assert summary.inserted_count == 2
    assert summary.rejected_count == 0


@pytest.mark.asyncio
async def test_sweep_stale_replicas_use_case_iterates_in_chunks() -> None:
    uow = FakeDataPlaneUnitOfWork()
    uow.replica_records.sweep_counts_queue = [500, 120]

    use_case = SweepStaleReplicasUseCase(uow=uow)
    res = await use_case.execute(
        SweepStaleReplicasCommand(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="meters",
            current_generation=5,
            chunk_size=500,
            trace_id="trc_sweep_01",
        )
    )
    assert res.is_ok is True
    summary = res.value
    assert summary.total_tombstoned == 620
    assert summary.chunks_processed == 2
    assert uow.commit_count == 2
