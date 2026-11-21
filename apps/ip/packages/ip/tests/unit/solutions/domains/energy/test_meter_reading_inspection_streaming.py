"""Comprehensive unit tests for Meter Reading Inspection, Vectorized Streaming Engine, and Platform Replay."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from database.olap import InMemoryOlapAdapter
from ip.engine.application.replay.ip_replay_service import IpReplayApplicationService
from ip.engine.application.vectorized_streaming_engine import VectorizedStreamingEngine
from ip.engine.domain.intervals.enums import BatchManifestStatus
from ip.engine.domain.intervals.models import BatchManifest, BatchReconciliationSummary
from ip.engine.domain.normalization.dtos import TransformationContext
from ip.engine.domain.replay.models import IpReplayAuditRecord
from ip.engine.domain.replay.ports import IpReplayAuditRepositoryPort
from ip.engine.ports.outbound.batch_manifest_repository_port import (
    BatchManifestRepositoryPort,
)
from ip.solutions.domains.energy.canonical import CanonicalMeterReadingDTO
from ip.solutions.domains.energy.inspection_dto import (
    MeterReadingSearchFilterDTO,
)
from ip.solutions.domains.energy.inspection_service import (
    MeterReadingInspectionService,
)
from ip.solutions.domains.energy.landis.normalize_landis_meter_readings import (
    normalize_landis_meter_reading,
)
from ip.solutions.domains.energy.stitches.backfill.hes1_file_backfill_stitch import (
    HES1_FILE_BACKFILL_STITCH,
)
from ip.solutions.domains.energy.stitches.backfill.hes2_kafka_backfill_stitch import (
    HES2_KAFKA_BACKFILL_STITCH,
)
from ip.solutions.domains.energy.stitches.continuous_stream.hes_continuous_meter_readings_worker import (
    HesContinuousMeterReadingsWorker,
)
from pubsub import KafkaPublisherAdapter
from replay.domain.dtos import (
    ExecuteReplayCommandDTO,
    ReplayPreviewRequestDTO,
    ReplayStage,
    ReplayStatus,
)
from replay.domain.enums import ReplayTargetType
from seedwork.domain.types import JsonValue
from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage
from storage.domain.enums import CompressionCodec


class InMemoryBatchManifestRepository(BatchManifestRepositoryPort):
    def __init__(self) -> None:
        self.manifests: dict[str, BatchManifest] = {}

    async def save(self, manifest: BatchManifest) -> None:
        self.manifests[manifest.id] = manifest

    async def get_by_id(self, batch_id: str, tenant_id: str) -> BatchManifest | None:
        m = self.manifests.get(batch_id)
        if m and m.tenant_id == tenant_id:
            return m
        return None

    async def get_by_sha256(
        self, tenant_id: str, connection_id: str, payload_sha256: str
    ) -> BatchManifest | None:
        for m in self.manifests.values():
            if m.tenant_id == tenant_id and m.payload_sha256 == payload_sha256:
                return m
        return None

    async def list_by_connection(
        self, tenant_id: str, *, connection_id: str | None = None, limit: int = 50
    ) -> Sequence[BatchManifest]:
        res = [m for m in self.manifests.values() if m.tenant_id == tenant_id]
        if connection_id:
            res = [m for m in res if m.connection_id == connection_id]
        return res[:limit]

    async def get_reconciliation_summary(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
    ) -> BatchReconciliationSummary:
        manifests = [m for m in self.manifests.values() if m.tenant_id == tenant_id]
        if connection_id:
            manifests = [m for m in manifests if m.connection_id == connection_id]
        raw = sum(m.raw_records_count for m in manifests)
        valid = sum(m.valid_canonical_count for m in manifests)
        quarantined = sum(m.quarantined_count for m in manifests)
        dups = sum(m.duplicates_dropped_count for m in manifests)
        completed = sum(1 for m in manifests if m.status == BatchManifestStatus.COMPLETED)
        failed = sum(1 for m in manifests if m.status == BatchManifestStatus.FAILED)
        in_flight = len(manifests) - completed - failed
        return BatchReconciliationSummary(
            tenant_id=tenant_id,
            connection_id=connection_id,
            total_batches=len(manifests),
            completed_batches=completed,
            in_flight_batches=in_flight,
            failed_batches=failed,
            raw_ingested_total=raw,
            duplicates_dropped_total=dups,
            valid_canonical_total=valid,
            quarantined_held_total=quarantined,
            in_flight_readings_total=0,
            is_zero_loss_balanced=(raw == dups + valid + quarantined),
        )


class InMemoryReplayAuditRepository(IpReplayAuditRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, IpReplayAuditRecord] = {}

    async def save(self, record: IpReplayAuditRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, replay_id: str, tenant_id: str) -> IpReplayAuditRecord | None:
        r = self.records.get(replay_id)
        if r and r.tenant_id == tenant_id:
            return r
        return None

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> IpReplayAuditRecord | None:
        for r in self.records.values():
            if r.tenant_id == tenant_id and r.idempotency_key == idempotency_key:
                return r
        return None

    async def list_by_target(
        self,
        tenant_id: str,
        target_type: ReplayTargetType,
        target_id: str,
        limit: int = 50,
    ) -> tuple[IpReplayAuditRecord, ...]:
        res = [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and r.target_type == target_type
            and r.target_id == target_id
        ]
        return tuple(res[:limit])


class InMemoryPayloadStorage(Aioboto3PayloadStorage):
    """In-memory stub extending Aioboto3PayloadStorage for fast zero-network unit testing."""

    def __init__(self) -> None:
        super().__init__(bucket="test-bucket", region="us-east-1")
        self.storage: dict[str, bytes] = {}

    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        key = f"tenants/{tenant_id}/inbound/{message_id}.bin"
        self.storage[f"s3://{self.bucket}/{key}"] = payload
        return f"s3://{self.bucket}/{key}"

    async def upload_partitioned(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        payload: bytes,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        key = self.build_partitioned_key(tenant_id, stream_name, batch_id, extension, compression)
        uri = f"s3://{self.bucket}/{key}"
        self.storage[uri] = payload
        return uri

    async def download(self, storage_uri: str, decompress: bool = True) -> bytes | None:
        return self.storage.get(storage_uri)


@pytest.mark.asyncio
async def test_meter_reading_inspection_search_micro_sample() -> None:
    olap_client = InMemoryOlapAdapter()
    manifest_repo = InMemoryBatchManifestRepository()

    # Pre-seed ClickHouse OLAP with 50 readings for meter MTR-100
    base_time = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    olap_rows = [
        {
            "tenant_id": "bescom",
            "meter_serial_number": "MTR-100",
            "interval_end_utc": (base_time + timedelta(minutes=15 * i)).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "service_point_id": "SP-99",
            "connection_id": "conn_hes",
            "batch_id": "bat_test_001",
            "scaled_kwh_delivered": 1.25,
            "scaled_kwh_received": 0.0,
            "voltage_v": 240.0,
            "quality_status": "VALID",
            "parquet_row_offset": i,
            "trace_id": f"trc_{i}",
            "correlation_id": "corr_001",
        }
        for i in range(50)
    ]
    await olap_client.insert_batch("ip.meter_readings", olap_rows)

    # Pre-seed PostgreSQL BatchManifest
    manifest = BatchManifest(
        id="bat_test_001",
        tenant_id="bescom",
        trace_id="trc_test_001",
        connection_id="conn_hes",
        app_id="energy_hes",
        stream_name="ami_intervals",
        l1_raw_uri="s3://bronze/bescom/bat_test_001.raw.zst",
        l3_canonical_uri="s3://silver/bescom/bat_test_001.parquet",
        payload_sha256="sha256_dummy",
        payload_size_bytes=512_000,
        window_start_utc=base_time,
        window_end_utc=base_time + timedelta(minutes=15 * 50),
        raw_ingested_count=50,
        valid_canonical_count=50,
        quarantined_held_count=0,
        status=BatchManifestStatus.COMPLETED,
    )
    await manifest_repo.save(manifest)

    inspection_service = MeterReadingInspectionService(olap_client, manifest_repo)

    # 1. Test Search (< 2s SLA)
    filter_dto = MeterReadingSearchFilterDTO(
        tenant_id="bescom",
        meter_serial_number="MTR-100",
        limit=50,
        offset=0,
    )
    summary, rows = await inspection_service.search(filter_dto)
    assert summary.meter_serial_number == "MTR-100"
    assert summary.total_readings_24h == 50
    assert summary.total_kwh_delivered_24h == 62.5  # 50 * 1.25
    assert summary.average_voltage_v == 240.0
    assert len(rows) == 50

    # 2. Test Micro-Sample (< 50ms SLA)
    micro_sample = await inspection_service.get_micro_sample(
        batch_id="bat_test_001",
        tenant_id="bescom",
        limit=50,
    )
    assert micro_sample.batch_id == "bat_test_001"
    assert micro_sample.total_count == 50
    assert micro_sample.valid_count == 50
    assert micro_sample.quarantined_count == 0
    assert len(micro_sample.micro_sample_records) == 50


@pytest.mark.asyncio
async def test_vectorized_streaming_engine_zero_loss_reconciliation() -> None:
    storage = InMemoryPayloadStorage()
    olap_client = InMemoryOlapAdapter()
    manifest_repo = InMemoryBatchManifestRepository()

    engine = VectorizedStreamingEngine(
        storage=storage,
        olap_client=olap_client,
        manifest_repo=manifest_repo,
    )

    # Create raw Bronze payload with 3 readings: 2 valid, 1 invalid (missing meter)
    raw_payload_data = [
        {
            "meter_serial_number": "MTR-A",
            "timestamp": "2026-11-20T12:00:00Z",
            "energy_kwh": 2.5,
            "voltage": 230.0,
        },
        {
            "meter_serial_number": "MTR-B",
            "timestamp": "2026-11-20T12:00:00Z",
            "energy_kwh": 3.0,
            "voltage": 232.0,
        },
        {
            "meter_serial_number": "",
            "timestamp": "2026-11-20T12:00:00Z",
            "energy_kwh": 1.0,
        },  # Invalid -> quarantined
    ]
    raw_bytes = json.dumps(raw_payload_data).encode("utf-8")
    bronze_uri = await storage.upload_partitioned(
        tenant_id="utility_bescom",
        stream_name="meter_intervals",
        batch_id="bat_rec_001",
        payload=raw_bytes,
        extension="raw.json",
    )

    def format_silver(dto: CanonicalMeterReadingDTO) -> dict[str, JsonValue]:
        return {
            "tenant_id": dto.tenant_id,
            "meter_serial_number": dto.meter_serial_number,
            "service_point_id": dto.service_point_id,
            "interval_end_utc": dto.interval_end_utc.isoformat(),
            "kwh_delivered": dto.kwh_delivered,
            "kwh_received": dto.kwh_received,
            "voltage_avg": dto.voltage_avg,
            "quality_flags": [f.value for f in dto.quality_flags],
        }

    def format_olap(
        dto: CanonicalMeterReadingDTO, ctx: TransformationContext, offset: int
    ) -> dict[str, JsonValue]:
        return {
            "tenant_id": dto.tenant_id,
            "meter_serial_number": dto.meter_serial_number,
            "interval_end_utc": dto.interval_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "service_point_id": dto.service_point_id or "",
            "connection_id": ctx.connection_id,
            "batch_id": "bat_rec_001",
            "scaled_kwh_delivered": dto.kwh_delivered,
            "scaled_kwh_received": dto.kwh_received,
            "voltage_v": dto.voltage_avg,
            "quality_status": "VALID",
            "parquet_row_offset": offset,
            "trace_id": ctx.trace_id,
            "correlation_id": "bat_rec_001",
        }

    def validate_reading(dto: CanonicalMeterReadingDTO) -> bool:
        return bool(dto.meter_serial_number and dto.interval_end_utc)

    res = await engine.process_batch(
        tenant_id="utility_bescom",
        batch_id="bat_rec_001",
        connection_id="conn_landis",
        stream_name="meter_intervals",
        bronze_uri=bronze_uri,
        normalizer_func=normalize_landis_meter_reading,
        olap_table="ip.meter_readings",
        olap_formatter=format_olap,
        silver_formatter=format_silver,
        validator_func=validate_reading,
    )

    assert res.is_ok
    manifest = res.unwrap()
    assert manifest.status == BatchManifestStatus.COMPLETED
    assert manifest.raw_ingested_count == 3
    assert manifest.valid_canonical_count == 2
    assert manifest.quarantined_held_count == 1
    # Zero-loss check: raw == valid + quarantined (3 == 2 + 1)
    assert manifest.reconciliation_counts.is_balanced()

    # Verify ClickHouse received the 2 valid readings
    ch_rows = await olap_client.execute_query(
        "SELECT * FROM ip.meter_readings WHERE tenant_id = 'utility_bescom' ORDER BY meter_serial_number ASC"
    )
    assert len(ch_rows) == 2
    assert ch_rows[0]["meter_serial_number"] == "MTR-A"
    assert ch_rows[1]["meter_serial_number"] == "MTR-B"


@pytest.mark.asyncio
async def test_ip_replay_service_preview_execute() -> None:
    storage = InMemoryPayloadStorage()
    manifest_repo = InMemoryBatchManifestRepository()
    audit_repo = InMemoryReplayAuditRepository()

    # Pre-seed batch manifest and Bronze raw payload
    manifest = BatchManifest(
        id="bat_rpl_001",
        tenant_id="utility_bescom",
        trace_id="trc_rpl_001",
        connection_id="conn_itron",
        app_id="energy_hes",
        stream_name="ami_stream",
        l1_raw_uri="s3://test-bucket/tenants/utility_bescom/bat_rpl_001.raw.json",
        l3_canonical_uri="s3://test-bucket/tenants/utility_bescom/bat_rpl_001.silver.json",
        payload_sha256="dummy_sha",
        payload_size_bytes=1000,
        window_start_utc=datetime.now(UTC),
        window_end_utc=datetime.now(UTC),
        raw_ingested_count=100,
        valid_canonical_count=98,
        quarantined_held_count=2,
        status=BatchManifestStatus.COMPLETED,
    )
    await manifest_repo.save(manifest)
    await storage.upload("utility_bescom", "bat_rpl_001", b'{"test": "payload"}')
    storage.storage["s3://test-bucket/tenants/utility_bescom/bat_rpl_001.raw.json"] = (
        b'{"test": "payload"}'
    )

    replay_service = IpReplayApplicationService(
        storage=storage,
        manifest_repo=manifest_repo,
        ledger_repo=audit_repo,
    )

    # 1. Replay Preview
    preview_req = ReplayPreviewRequestDTO(
        target_id="bat_rpl_001",
        tenant_id="utility_bescom",
        target_stage=ReplayStage.STAGE_1_RAW_INGRESS,
    )
    preview_res = await replay_service.preview_replay(preview_req)
    assert preview_res.is_ok
    preview = preview_res.unwrap()
    assert preview.total_record_count == 100
    assert preview.target_stage == ReplayStage.STAGE_1_RAW_INGRESS

    # 2. Replay Execution
    exec_cmd = ExecuteReplayCommandDTO(
        target_id="bat_rpl_001",
        tenant_id="utility_bescom",
        target_stage=ReplayStage.STAGE_1_RAW_INGRESS,
        actor="sre_support",
        reason="VEE rule re-execution",
        idempotency_key="idem_token_abc",
    )
    exec_res = await replay_service.execute_replay(exec_cmd)
    assert exec_res.is_ok
    exec_dto = exec_res.unwrap()
    assert exec_dto.status == ReplayStatus.IN_FLIGHT

    # 3. Verify App-Owned Relational Audit Record
    records = await audit_repo.list_by_target(
        "utility_bescom", ReplayTargetType.BATCH, "bat_rpl_001"
    )
    assert len(records) == 1
    assert records[0].id == exec_dto.replay_id
    assert records[0].actor == "sre_support"
    assert records[0].status == ReplayStatus.COMPLETED


@pytest.mark.asyncio
async def test_hes_continuous_worker_dual_path_execution() -> None:
    storage = InMemoryPayloadStorage()
    olap_client = InMemoryOlapAdapter()
    kafka_producer = KafkaPublisherAdapter(use_in_memory=True)

    worker = HesContinuousMeterReadingsWorker(
        tenant_id="utility_kwh",
        storage=storage,
        olap_client=olap_client,
        publisher=kafka_producer,
        egress_topic="mdm.meter_readings.inbound",
        batch_size_threshold=2,  # Flush after 2 readings
        max_window_seconds=60.0,
    )

    r1 = CanonicalMeterReadingDTO(
        meter_serial_number="MTR-1",
        tenant_id="utility_kwh",
        interval_end_utc=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        kwh_delivered=1.5,
        kwh_received=0.0,
        voltage_avg=240.0,
    )
    r2 = CanonicalMeterReadingDTO(
        meter_serial_number="MTR-2",
        tenant_id="utility_kwh",
        interval_end_utc=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        kwh_delivered=2.0,
        kwh_received=0.0,
        voltage_avg=239.5,
    )

    # Ingest r1 (Fast-path Kafka message emitted, Coalescer size = 1)
    await worker.ingest_reading(r1)
    assert len(kafka_producer.in_memory_records) == 1
    assert kafka_producer.in_memory_records[0][0] == "mdm.meter_readings.inbound"

    # Ingest r2 (Fast-path Kafka message emitted, Coalescer hits threshold 2 -> flushes to S3 & ClickHouse!)
    await worker.ingest_reading(r2)
    assert len(kafka_producer.in_memory_records) == 2

    # Verify ClickHouse OLAP received the 2 coalesced records
    olap_records = await olap_client.execute_query(
        "SELECT * FROM ip.meter_readings WHERE tenant_id = 'utility_kwh' ORDER BY meter_serial_number ASC"
    )
    assert len(olap_records) == 2
    assert olap_records[0]["meter_serial_number"] == "MTR-1"
    assert olap_records[1]["meter_serial_number"] == "MTR-2"


def test_stitch_blueprint_specs_defined() -> None:
    assert HES1_FILE_BACKFILL_STITCH.id == "energy.hes1_file_backfill"
    assert HES1_FILE_BACKFILL_STITCH.destination == "mdm.meter_readings.inbound"

    assert HES2_KAFKA_BACKFILL_STITCH.id == "energy.hes2_kafka_backfill"
    assert HES2_KAFKA_BACKFILL_STITCH.destination == "mdm.meter_readings.inbound"
