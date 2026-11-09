"""Unit tests for Vectorized Interval Normalizer and Columnar Rollup Repository.

Verifies the 3 Gold-Standard Invariants:
  1. Zero-Copy Arrow IPC Streaming (`encode_arrow_ipc_stream` / `decode_arrow_ipc_stream` + `insert_arrow_batch`)
  2. Idempotent Deduplication via `ReplacingMergeTree(updated_at_utc)`
  3. Real-Time Pre-Aggregated `AggregatingMergeTree` Materialized Views (`mv_interval_readings_hourly`, `mv_daily_tou_rollups`, `mv_daily_completeness`)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from ip.engine.adapters.outbound.database.data_plane.trace_specs import (
    map_manifest_status_to_trace_status,
)
from ip.engine.adapters.outbound.intervals import (
    ARROW_IPC_STREAM_MAGIC,
    ColumnarIntervalRollupRepositoryAdapter,
    VectorizedIntervalBatchNormalizerAdapter,
    decode_arrow_ipc_stream,
    encode_arrow_ipc_stream,
)
from ip.engine.adapters.outbound.intervals.interval_batch_normalizer import _parse_timestamp
from ip.engine.application.use_cases.intervals.process_interval_batch_use_case import (
    _BATCH_LOCKS,
    _acquire_manifest_lock,
)
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    CimQualityStatus,
    IntervalPayloadFormat,
    TariffBucket,
)
from ip.engine.domain.intervals.models import BatchManifest, IntervalReading
from ip.engine.domain.trace import IpTraceStatus
from tests.helpers.worker_fakes import InMemoryBatchManifestRepo


def test_arrow_ipc_stream_codec_binary_roundtrip() -> None:
    ts0 = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    ts1 = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
    readings = (
        IntervalReading(
            tenant_id="tenant_01",
            connection_id="conn_01",
            gem_device_id="gem_dev_001",
            source_meter_id="DEV_001",
            endpoint_location_id="LOC-DEV_001",
            feeder_id="FDR_10",
            substation_id="SUB_01",
            tariff_bucket=TariffBucket.SHOULDER,
            quality_status=CimQualityStatus.VALID,
            interval_end_utc=ts0,
            scaled_kwh_delivered=Decimal("1.2500"),
            scaled_kwh_received=Decimal("0.0000"),
            reactive_kvarh=Decimal("0.1000"),
            voltage_v=239.8,
            source_batch_id="ip_ibatch_01",
            parquet_row_offset=0,
            trace_id="trc_01",
            updated_at_utc=ts1,
        ),
        IntervalReading(
            tenant_id="tenant_01",
            connection_id="conn_01",
            gem_device_id="gem_dev_001",
            source_meter_id="DEV_001",
            endpoint_location_id="LOC-DEV_001",
            feeder_id="FDR_10",
            substation_id="SUB_01",
            tariff_bucket=TariffBucket.SHOULDER,
            quality_status=CimQualityStatus.VALID,
            interval_end_utc=ts1,
            scaled_kwh_delivered=Decimal("1.5000"),
            scaled_kwh_received=Decimal("0.1000"),
            reactive_kvarh=Decimal("0.1200"),
            voltage_v=240.1,
            source_batch_id="ip_ibatch_01",
            parquet_row_offset=1,
            trace_id="trc_01",
            updated_at_utc=ts1,
        ),
    )

    binary_stream = encode_arrow_ipc_stream(readings)
    assert binary_stream.startswith(ARROW_IPC_STREAM_MAGIC)

    decoded_res = decode_arrow_ipc_stream(binary_stream)
    assert decoded_res.is_ok is True
    decoded = decoded_res.unwrap()
    assert len(decoded) == 2
    assert decoded[0].gem_device_id == "gem_dev_001"
    assert decoded[0].scaled_kwh_delivered == Decimal("1.2500")
    assert decoded[1].scaled_kwh_delivered == Decimal("1.5000")
    assert decoded[1].parquet_row_offset == 1


def test_columnar_processor_quarantines_spike_via_rolling_median() -> None:
    processor = VectorizedIntervalBatchNormalizerAdapter()
    base_time = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    readings = [
        {
            "source_meter_id": "DEV_SPIKE_01",
            "feeder_id": "FDR_01",
            "substation_id": "SUB_01",
            "interval_end_utc": (base_time + timedelta(minutes=15 * i)).isoformat(),
            "kwh_delivered": "1.2000",
            "voltage_v": 240.0,
        }
        for i in range(5)
    ]
    # Add an exact duplicate of reading 0 to verify intra-batch deduplication
    readings.append(dict(readings[0]))
    # Add an anomalous 450.0 spike at interval 5 (> VEE ceiling and > 10x median)
    readings.append(
        {
            "source_meter_id": "DEV_SPIKE_01",
            "feeder_id": "FDR_01",
            "substation_id": "SUB_01",
            "interval_end_utc": (base_time + timedelta(minutes=15 * 5)).isoformat(),
            "kwh_delivered": "450.0000",
            "voltage_v": 240.0,
        }
    )

    raw_bytes = json.dumps(readings).encode("utf-8")
    res = processor.normalize_batch(
        batch_id="ip_ibatch_test01",
        tenant_id="tenant_utility_01",
        connection_id="conn_01",
        stream_name="interval_readings_15m",
        trace_id="trc_spike_01",
        raw_payload_bytes=raw_bytes,
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
    )
    assert res.is_ok is True
    artifact = res.unwrap()

    assert artifact.counts.raw_ingested == 7
    assert artifact.counts.duplicates_dropped == 1
    assert artifact.counts.valid_canonical == 5
    assert artifact.counts.quarantined_held == 1
    assert artifact.counts.is_balanced() is True

    quarantined = [
        r
        for r in artifact.canonical_readings
        if r.quality_status is CimQualityStatus.QUARANTINED_SPIKE
    ]
    assert len(quarantined) == 1
    assert quarantined[0].scaled_kwh_delivered == Decimal("450.0000")
    assert quarantined[0].quarantine_reason is not None


def test_columnar_processor_collapses_storm_feeder_outages() -> None:
    processor = VectorizedIntervalBatchNormalizerAdapter()
    detected_iso = datetime(2026, 11, 9, 18, 15, tzinfo=UTC).isoformat()

    readings = []
    # 30 zero-voltage endpoints on FDR_STORM_01 (>= 25 threshold -> 1 collapsed FeederOutageCluster)
    for idx in range(30):
        readings.append(
            {
                "source_meter_id": f"DEV_STORM_{idx:03d}",
                "feeder_id": "FDR_STORM_01",
                "substation_id": "SUB_STORM_A",
                "interval_end_utc": detected_iso,
                "kwh_delivered": "0.0000",
                "voltage_v": 0.0,
            }
        )
    # 2 zero-voltage endpoints on FDR_LOCAL_02 (< 25 threshold -> 2 individual clusters)
    for idx in range(2):
        readings.append(
            {
                "source_meter_id": f"DEV_LOCAL_{idx:03d}",
                "feeder_id": "FDR_LOCAL_02",
                "substation_id": "SUB_LOCAL_B",
                "interval_end_utc": detected_iso,
                "kwh_delivered": "0.0000",
                "voltage_v": 0.0,
            }
        )

    res = processor.normalize_batch(
        batch_id="ip_ibatch_storm01",
        tenant_id="tenant_utility_01",
        connection_id="conn_01",
        stream_name="interval_readings_15m",
        trace_id="trc_storm_01",
        raw_payload_bytes=json.dumps(readings).encode("utf-8"),
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
    )
    assert res.is_ok is True
    artifact = res.unwrap()

    assert len(artifact.outage_clusters) == 3
    storm_clusters = [c for c in artifact.outage_clusters if c.feeder_id == "FDR_STORM_01"]
    local_clusters = [c for c in artifact.outage_clusters if c.feeder_id == "FDR_LOCAL_02"]
    assert len(storm_clusters) == 1
    assert storm_clusters[0].outage_meter_count == 30
    assert len(local_clusters) == 2
    assert all(c.outage_meter_count == 1 for c in local_clusters)


@pytest.mark.asyncio
async def test_interval_rollup_repo_replacing_merge_tree_idempotent_replay() -> None:
    processor = VectorizedIntervalBatchNormalizerAdapter()
    repo = ColumnarIntervalRollupRepositoryAdapter()

    service_day = date(2026, 11, 9)
    readings = [
        {
            "source_meter_id": "DEV_REPLAY_01",
            "feeder_id": "FDR_01",
            "substation_id": "SUB_01",
            "interval_end_utc": datetime(2026, 11, 9, 19, 15, tzinfo=UTC).isoformat(),
            "kwh_delivered": "2.0000",
            "kwh_received": "0.5000",
            "voltage_v": 238.5,
        }
    ]
    artifact1 = processor.normalize_batch(
        batch_id="ip_ibatch_replay_1",
        tenant_id="tenant_utility_01",
        connection_id="conn_01",
        stream_name="interval_readings_15m",
        trace_id="trc_replay_1",
        raw_payload_bytes=json.dumps(readings).encode("utf-8"),
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
    ).unwrap()

    ins1 = await repo.insert_arrow_batch(
        tenant_id="tenant_utility_01",
        stream_name="interval_readings_15m",
        batch_id="ip_ibatch_replay_1",
        arrow_ipc_bytes=artifact1.arrow_ipc_bytes,
    )
    assert ins1.is_ok is True

    # Replay the exact same device + interval with updated kwh_delivered (2.5000 instead of 2.0000)
    readings[0]["kwh_delivered"] = "2.5000"
    artifact2 = processor.normalize_batch(
        batch_id="ip_ibatch_replay_2",
        tenant_id="tenant_utility_01",
        connection_id="conn_01",
        stream_name="interval_readings_15m",
        trace_id="trc_replay_2",
        raw_payload_bytes=json.dumps(readings).encode("utf-8"),
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
    ).unwrap()

    ins2 = await repo.insert_arrow_batch(
        tenant_id="tenant_utility_01",
        stream_name="interval_readings_15m",
        batch_id="ip_ibatch_replay_2",
        arrow_ipc_bytes=artifact2.arrow_ipc_bytes,
    )
    assert ins2.is_ok is True

    # Verify ReplacingMergeTree deduplicated the interval and MV rollups were not double-counted
    curve_res = await repo.get_device_load_curve(
        tenant_id="tenant_utility_01",
        source_meter_id="DEV_REPLAY_01",
        service_date=service_day,
    )
    assert curve_res.is_ok is True
    curve = curve_res.unwrap()
    assert len(curve) == 1
    assert curve[0].scaled_kwh_delivered == Decimal("2.5000")
    assert curve[0].source_batch_id == "ip_ibatch_replay_2"

    tou_res = await repo.get_daily_tou_rollups(
        tenant_id="tenant_utility_01",
        service_date=service_day,
        source_meter_id="DEV_REPLAY_01",
    )
    assert tou_res.is_ok is True
    tou_rows = tou_res.unwrap()
    assert len(tou_rows) == 1
    assert tou_rows[0].kwh_peak == Decimal("2.5000")
    assert tou_rows[0].valid_intervals == 1


@pytest.mark.asyncio
async def test_interval_rollup_repo_materialized_views_compute_tou_completeness() -> None:
    processor = VectorizedIntervalBatchNormalizerAdapter()
    repo = ColumnarIntervalRollupRepositoryAdapter()

    service_day = date(2026, 11, 9)
    readings = [
        # Off-Peak (02:15 UTC)
        {
            "source_meter_id": "DEV_MV_01",
            "feeder_id": "FDR_99",
            "substation_id": "SUB_99",
            "interval_end_utc": datetime(2026, 11, 9, 2, 15, tzinfo=UTC).isoformat(),
            "kwh_delivered": "0.8000",
            "voltage_v": 241.0,
        },
        # Shoulder (10:15 UTC)
        {
            "source_meter_id": "DEV_MV_01",
            "feeder_id": "FDR_99",
            "substation_id": "SUB_99",
            "interval_end_utc": datetime(2026, 11, 9, 10, 15, tzinfo=UTC).isoformat(),
            "kwh_delivered": "1.4000",
            "voltage_v": 240.0,
        },
        # Peak (18:15 UTC)
        {
            "source_meter_id": "DEV_MV_01",
            "feeder_id": "FDR_99",
            "substation_id": "SUB_99",
            "interval_end_utc": datetime(2026, 11, 9, 18, 15, tzinfo=UTC).isoformat(),
            "kwh_delivered": "3.1000",
            "voltage_v": 238.0,
        },
    ]
    artifact = processor.normalize_batch(
        batch_id="ip_ibatch_mv_01",
        tenant_id="tenant_utility_01",
        connection_id="conn_01",
        stream_name="interval_readings_15m",
        trace_id="trc_mv_01",
        raw_payload_bytes=json.dumps(readings).encode("utf-8"),
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
    ).unwrap()

    await repo.insert_arrow_batch(
        tenant_id="tenant_utility_01",
        stream_name="interval_readings_15m",
        batch_id="ip_ibatch_mv_01",
        arrow_ipc_bytes=artifact.arrow_ipc_bytes,
    )

    comp_res = await repo.get_daily_completeness(
        tenant_id="tenant_utility_01",
        connection_id="conn_01",
        service_date=service_day,
        stream_name="interval_readings_15m",
    )
    assert comp_res.is_ok is True
    completeness = comp_res.unwrap()
    assert len(completeness) == 1
    assert completeness[0].expected_intervals_total == 96
    assert completeness[0].valid_intervals_total == 3
    assert completeness[0].completeness_percentage == round((3 / 96) * 100.0, 2)


def test_parse_timestamp_supports_native_datetime() -> None:
    now_utc = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert _parse_timestamp(now_utc) == now_utc

    naive_dt = datetime(2026, 11, 9, 12, 0)
    assert _parse_timestamp(naive_dt) == now_utc


def test_parse_timestamp_supports_iso_strings() -> None:
    now_utc = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    iso_str = "2026-11-09T12:00:00Z"
    assert _parse_timestamp(iso_str) == now_utc


def test_map_manifest_status_quarantined_maps_to_dead_lettered() -> None:
    assert (
        map_manifest_status_to_trace_status(BatchManifestStatus.QUARANTINED)
        is IpTraceStatus.DEAD_LETTERED
    )
    assert (
        map_manifest_status_to_trace_status(BatchManifestStatus.COMPLETED)
        is IpTraceStatus.PROCESSED
    )
    assert map_manifest_status_to_trace_status(BatchManifestStatus.FAILED) is IpTraceStatus.FAILED


@pytest.mark.asyncio
async def test_acquire_manifest_lock_evicts_after_release() -> None:
    t_id = "test_ten_lock"
    b_id = "batch_lock_01"
    key = (t_id, b_id)

    assert key not in _BATCH_LOCKS
    async with _acquire_manifest_lock(t_id, b_id):
        assert key in _BATCH_LOCKS
        assert _BATCH_LOCKS[key].ref_count == 1
    assert key not in _BATCH_LOCKS


@pytest.mark.asyncio
async def test_in_memory_batch_manifest_repo_reconciliation_summary() -> None:
    now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    repo = InMemoryBatchManifestRepo()
    m1 = BatchManifest.create_ingested(
        tenant_id="ten_recon_test",
        connection_id="conn_recon_01",
        app_id="app_ami",
        stream_name="interval_readings_15m",
        l1_raw_uri="s3://vault/raw1.parquet",
        payload_sha256="sha1",
        payload_size_bytes=1000,
        raw_ingested_count=10,
        window_start_utc=now,
        window_end_utc=now,
    )
    m1.status = BatchManifestStatus.COMPLETED
    m1.valid_canonical_count = 10
    m1.duplicates_dropped_count = 0
    m1.quarantined_held_count = 0
    await repo.save(m1)

    summary = await repo.get_reconciliation_summary("ten_recon_test", connection_id="conn_recon_01")
    assert summary.total_batches == 1
    assert summary.completed_batches == 1
    assert summary.in_flight_batches == 0
    assert summary.failed_batches == 0
    assert summary.raw_ingested_total == 10
    assert summary.valid_canonical_total == 10
    assert summary.is_zero_loss_balanced is True
