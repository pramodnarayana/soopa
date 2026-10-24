"""Unit tests for IngestStreamBatchUseCase verifying atomic at-least-once handshake and deduplication."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.ingestion.ingest_stream_batch_use_case import (
    IngestStreamBatchCommand,
    IngestStreamBatchUseCase,
)
from ip.engine.domain.enums import AckVerdict, IngestionMode
from ip.engine.domain.exceptions import PayloadNotFoundError, Result
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    RawMessageDTO,
)
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from seedwork.domain.types import JsonDict, JsonValue


class FakeInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

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


class FakeDataPlaneUnitOfWork(IpDataPlaneUnitOfWorkPort):
    def __init__(self, should_fail_commit: bool = False) -> None:
        self.inbound_records = FakeInboundRecordRepository()
        self.committed = False
        self.rolled_back = False
        self._should_fail_commit = should_fail_commit

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
        if self._should_fail_commit:
            raise RuntimeError("Database connection lost during commit")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeTieredStorageAdapter(TieredStoragePort):
    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        is_inlined = len(payload_bytes) <= 65536
        raw_b64 = base64.b64encode(payload_bytes).decode("ascii")
        json_data: dict[str, object] = (
            dict(parsed_payload)
            if isinstance(parsed_payload, dict)
            else ({"__wrapped_scalar__": parsed_payload} if parsed_payload is not None else {})
        )
        json_data["__raw_b64__"] = raw_b64
        return TieredStorageResultDTO(
            is_inlined=is_inlined,
            raw_payload=json_data if is_inlined else None,
            s3_key="s3://lake/blobs/msg.bin" if not is_inlined else None,
            payload_size_bytes=len(payload_bytes),
            payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        if result.raw_payload and "__raw_b64__" in result.raw_payload:
            return Result.ok(base64.b64decode(str(result.raw_payload["__raw_b64__"])))
        return Result.ok(b"")


class FakeDecoder(InboundPayloadDecoderPort):
    def decode(self, content_type: str, raw_body: bytes) -> Result[JsonDict, Exception]:
        try:
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                return Result.ok(parsed)
            return Result.ok({"data": parsed})
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Result.ok({"raw": raw_body.decode("utf-8", errors="replace")})


@pytest.mark.asyncio
async def test_ingest_stream_batch_success() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    decoder = FakeDecoder()
    use_case = IngestStreamBatchUseCase(uow=uow, tiered_storage=storage, decoder=decoder)

    messages = [
        RawMessageDTO(
            message_id="msg_001",
            raw_payload=b'{"device_id":"meter_1","kwh":10.5}',
            partition_id="part_0",
            broker_offset="101",
        ),
        RawMessageDTO(
            message_id="msg_002",
            raw_payload=b'{"device_id":"meter_2","kwh":12.1}',
            partition_id="part_0",
            broker_offset="102",
        ),
    ]
    batch = RawMessageBatchDTO(stream_name="readings", messages=messages)
    cmd = IngestStreamBatchCommand(
        tenant_id="tenant_x",
        connection_id="conn_kafka",
        app_id="grid_streamer",
        stream_name="readings",
        batch=batch,
    )

    result = await use_case.execute(cmd)

    assert result.verdict == AckVerdict.ACK
    assert result.records_ingested == 2
    assert result.duplicates_skipped == 0
    assert len(uow.inbound_records.records) == 2
    assert uow.committed is True

    record = next(iter(uow.inbound_records.records.values()))
    assert record.ingestion_mode == IngestionMode.STREAM_SUBSCRIBE
    assert record.external_event_id == "msg_001"
    assert record.request_headers.get("x-stream-partition") == "part_0"
    assert record.request_headers.get("x-stream-offset") == "101"


@pytest.mark.asyncio
async def test_ingest_stream_batch_deduplication_skips_existing() -> None:
    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    decoder = FakeDecoder()
    use_case = IngestStreamBatchUseCase(uow=uow, tiered_storage=storage, decoder=decoder)

    # Pre-seed record with message_id "msg_001"
    existing = InboundRecord.create(
        tenant_id="tenant_x",
        connection_id="conn_kafka",
        app_id="grid_streamer",
        stream_name="readings",
        payload_bytes=b"{}",
        is_inlined=True,
        external_event_id="msg_001",
    )
    await uow.inbound_records.save(existing)

    messages = [
        RawMessageDTO(
            message_id="msg_001",  # duplicate!
            raw_payload=b'{"device_id":"meter_1","kwh":10.5}',
        ),
        RawMessageDTO(
            message_id="msg_002",  # new!
            raw_payload=b'{"device_id":"meter_2","kwh":12.1}',
        ),
    ]
    batch = RawMessageBatchDTO(stream_name="readings", messages=messages)
    cmd = IngestStreamBatchCommand(
        tenant_id="tenant_x",
        connection_id="conn_kafka",
        app_id="grid_streamer",
        stream_name="readings",
        batch=batch,
    )

    result = await use_case.execute(cmd)

    assert result.verdict == AckVerdict.ACK
    assert result.records_ingested == 1
    assert result.duplicates_skipped == 1
    assert len(uow.inbound_records.records) == 2  # 1 pre-seeded + 1 newly ingested


@pytest.mark.asyncio
async def test_ingest_stream_batch_failure_returns_nack() -> None:
    uow = FakeDataPlaneUnitOfWork(should_fail_commit=True)
    storage = FakeTieredStorageAdapter()
    decoder = FakeDecoder()
    use_case = IngestStreamBatchUseCase(uow=uow, tiered_storage=storage, decoder=decoder)

    messages = [
        RawMessageDTO(
            message_id="msg_001",
            raw_payload=b'{"device_id":"meter_1"}',
        ),
    ]
    batch = RawMessageBatchDTO(stream_name="readings", messages=messages)
    cmd = IngestStreamBatchCommand(
        tenant_id="tenant_x",
        connection_id="conn_kafka",
        app_id="grid_streamer",
        stream_name="readings",
        batch=batch,
    )

    result = await use_case.execute(cmd)

    assert result.verdict == AckVerdict.NACK
    assert result.records_ingested == 0
    assert "Database connection lost during commit" in (result.error_message or "")


@pytest.mark.asyncio
async def test_ingest_stream_batch_deterministic_error_returns_reject() -> None:
    class FailingDecoder(InboundPayloadDecoderPort):
        def decode(self, *, content_type: str, raw_body: bytes) -> Result[JsonDict, Exception]:
            raise ValueError("Deterministic corrupt payload structure")

    uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    decoder = FailingDecoder()
    use_case = IngestStreamBatchUseCase(uow=uow, tiered_storage=storage, decoder=decoder)

    messages = [
        RawMessageDTO(
            message_id="msg_corrupt_1",
            raw_payload=b"INVALID_PAYLOAD_1",
        ),
        RawMessageDTO(
            message_id="msg_corrupt_2",
            raw_payload=b"INVALID_PAYLOAD_2",
        ),
    ]
    batch = RawMessageBatchDTO(stream_name="readings", messages=messages)
    cmd = IngestStreamBatchCommand(
        tenant_id="tenant_x",
        connection_id="conn_kafka",
        app_id="grid_streamer",
        stream_name="readings",
        batch=batch,
    )

    result = await use_case.execute(cmd)

    assert result.verdict == AckVerdict.REJECT
    assert result.records_ingested == 0
    assert "Deterministic corrupt payload structure" in (result.error_message or "")
    assert len(uow.inbound_records.records) == 2
    for record in uow.inbound_records.records.values():
        assert record.response_status_code == 422
        assert record.request_body is not None
        assert record.request_body.get("status") == "REJECTED"
        assert record.request_body.get("error") == "Deterministic corrupt payload structure"
        # Verify each rejected message's bytes are recoverable inline or via s3_key
        if record.request_s3_key is not None:
            assert record.request_s3_key.startswith("s3://")
        else:
            recovered_bytes = base64.b64decode(str(record.request_body["__raw_b64__"]))
            assert recovered_bytes in (b"INVALID_PAYLOAD_1", b"INVALID_PAYLOAD_2")
        assert record.external_event_id in ("msg_corrupt_1", "msg_corrupt_2")
