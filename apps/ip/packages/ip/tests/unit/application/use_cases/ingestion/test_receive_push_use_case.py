"""Unit tests for ReceivePushUseCase using in-memory test fakes."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from types import TracebackType

import pytest
from ip.engine.adapters.outbound.inbound.ack import JsonInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import (
    HmacSignatureVerifier,
    NoOpVerifier,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushUseCase,
)
from ip.engine.domain.exceptions import PayloadNotFoundError, Result
from ip.engine.domain.replication.enums import IngestionMode
from ip.engine.domain.replication.events import (
    FetchRecordRequestedEvent,
    InboundRecordCreatedEvent,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.quarantine_record_repository_port import (
    QuarantineRecordRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from seedwork.domain.types import JsonValue


class FakeInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        if rec and rec.tenant_id == tenant_id:
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
        target_ids = list(record_ids) or ([range_start] if range_start else [])
        return [
            self.records[rec_id]
            for rec_id in target_ids
            if rec_id in self.records and self.records[rec_id].tenant_id == tenant_id
        ]

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[InboundRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
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


class FakeDataPlaneUnitOfWork(IpDataPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.inbound_records = FakeInboundRecordRepository()
        self.committed = False

    @property
    def replica_records(self) -> ReplicaRecordRepositoryPort:
        raise NotImplementedError

    @property
    def replica_rejections(self) -> ReplicaRejectionRepositoryPort:
        raise NotImplementedError

    @property
    def normalized_records(self) -> NormalizedRecordRepositoryPort:
        raise NotImplementedError

    @property
    def global_entity_map(self) -> GlobalEntityMapRepositoryPort:
        raise NotImplementedError

    @property
    def outbound_records(self) -> OutboundRecordRepositoryPort:
        raise NotImplementedError

    @property
    def quarantine_records(self) -> QuarantineRecordRepositoryPort:
        raise NotImplementedError

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

    async def rollback(self) -> None:
        pass


class FakeTieredStorageAdapter(TieredStoragePort):
    async def store(
        self,
        *,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        return TieredStorageResultDTO(
            is_inlined=True,
            raw_payload=(
                dict(parsed_payload)
                if isinstance(parsed_payload, dict)
                else (
                    {"__wrapped_scalar__": parsed_payload} if parsed_payload is not None else None
                )
            ),
            s3_key=None,
            payload_size_bytes=len(payload_bytes),
            payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        return Result.ok(b"")


@pytest.mark.asyncio
async def test_receive_push_full_success() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    verifier = NoOpVerifier()
    decoder = StandardInboundPayloadDecoder()
    ack = JsonInboundAck(status_code=202)

    use_case = ReceivePushUseCase(
        uow=uow,
        tiered_storage=storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
    )

    cmd = ReceivePushCommand(
        tenant_id="tenant_alpha",
        connection_id="conn_source",
        stream_name="interval_readings",
        raw_payload=b'{"device_id":"dev_01","value":42}',
        headers={"Content-Type": "application/json"},
        external_event_id="evt_001",
    )

    result = await use_case.execute(cmd)

    assert result.status_code == 202
    assert result.is_verified is True
    assert result.is_duplicate is False
    assert result.record_id is not None
    assert uow.committed is True

    stored = await uow.inbound_records.get_by_id(result.record_id, "tenant_alpha")
    assert stored is not None
    assert stored.ingestion_mode == IngestionMode.PUSH_FULL
    assert stored.external_event_id == "evt_001"
    assert stored.stream_name == "interval_readings"

    event_types = [type(e) for e in stored.domain_events]
    assert InboundRecordCreatedEvent in event_types


@pytest.mark.asyncio
async def test_receive_push_verification_failure_rejects() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    verifier = HmacSignatureVerifier(
        signature_header="X-Signature", timestamp_header=None, prefix=""
    )
    decoder = StandardInboundPayloadDecoder()
    ack = JsonInboundAck(status_code=202)

    use_case = ReceivePushUseCase(
        uow=uow,
        tiered_storage=storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
    )

    cmd = ReceivePushCommand(
        tenant_id="tenant_alpha",
        connection_id="conn_source",
        stream_name="interval_readings",
        raw_payload=b'{"device_id":"dev_01","value":42}',
        headers={"X-Signature": "invalid_sig"},
        secret="valid_secret",
    )

    result = await use_case.execute(cmd)

    assert result.status_code == 401
    assert result.is_verified is False
    assert result.record_id is None
    assert len(uow.inbound_records.records) == 0


@pytest.mark.asyncio
async def test_receive_push_deduplication() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    verifier = NoOpVerifier()
    decoder = StandardInboundPayloadDecoder()
    ack = JsonInboundAck(status_code=202)

    use_case = ReceivePushUseCase(
        uow=uow,
        tiered_storage=storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
    )

    cmd = ReceivePushCommand(
        tenant_id="tenant_alpha",
        connection_id="conn_source",
        stream_name="interval_readings",
        raw_payload=b'{"device_id":"dev_01","value":42}',
        headers={},
        external_event_id="evt_002",
    )

    first_res = await use_case.execute(cmd)
    assert first_res.status_code == 202
    assert first_res.is_duplicate is False

    # Second push with identical external_event_id
    second_res = await use_case.execute(cmd)
    assert second_res.status_code == 202
    assert second_res.is_duplicate is True
    assert second_res.record_id == first_res.record_id
    assert len(uow.inbound_records.records) == 1


@pytest.mark.asyncio
async def test_receive_push_thin_emits_fetch_record_requested() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    verifier = NoOpVerifier()
    decoder = StandardInboundPayloadDecoder()
    ack = JsonInboundAck(status_code=202)

    use_case = ReceivePushUseCase(
        uow=uow,
        tiered_storage=storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
    )

    cmd = ReceivePushCommand(
        tenant_id="tenant_alpha",
        connection_id="conn_source",
        stream_name="records_alpha",
        raw_payload=b'{"notification":"record_updated","id":"rec_999"}',
        headers={},
        is_thin=True,
        thin_record_id="rec_999",
    )

    result = await use_case.execute(cmd)

    assert result.status_code == 202
    stored = await uow.inbound_records.get_by_id(result.record_id or "", "tenant_alpha")
    assert stored is not None
    assert stored.ingestion_mode == IngestionMode.PUSH_THIN

    events = stored.domain_events
    fetch_reqs = [e for e in events if isinstance(e, FetchRecordRequestedEvent)]
    assert len(fetch_reqs) == 1
    assert fetch_reqs[0].record_id == "rec_999"
    assert fetch_reqs[0].stream == "records_alpha"


@pytest.mark.asyncio
async def test_receive_push_json_array_success() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    verifier = NoOpVerifier()
    decoder = StandardInboundPayloadDecoder()
    ack = JsonInboundAck(status_code=202)

    use_case = ReceivePushUseCase(
        uow=uow,
        tiered_storage=storage,
        verifier=verifier,
        decoder=decoder,
        ack=ack,
    )

    cmd = ReceivePushCommand(
        tenant_id="tenant_arr",
        connection_id="conn_arr",
        stream_name="shipments",
        raw_payload=b'[{"id":"shp_1","status":"NEW"},{"id":"shp_2","status":"DISPATCHED"}]',
        headers={"Content-Type": "application/json"},
    )

    result = await use_case.execute(cmd)

    assert result.status_code == 202
    assert result.is_verified is True
    stored = await uow.inbound_records.get_by_id(result.record_id or "", "tenant_arr")
    assert stored is not None
    assert stored.request_body is not None
    assert "__wrapped_scalar__" in stored.request_body
    assert len(stored.request_body["__wrapped_scalar__"]) == 2
    assert stored.request_body["__wrapped_scalar__"][0]["id"] == "shp_1"
