"""Unit tests for storage codecs and in-memory micro-batch coalescer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from storage import (
    Aioboto3PayloadStorage,
    BatchFlusherPort,
    CompressionCodec,
    MicroBatchCoalescer,
    StorageCodec,
)


@dataclass(frozen=True, slots=True)
class DummyLogisticsPingDTO:
    ping_id: str
    vehicle_vin: str
    latitude: float
    longitude: float


class CapturingFlusher(BatchFlusherPort[DummyLogisticsPingDTO]):
    def __init__(self) -> None:
        self.flushed_batches: list[tuple[str, str, str, tuple[DummyLogisticsPingDTO, ...]]] = []

    async def flush_batch(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        records: tuple[DummyLogisticsPingDTO, ...],
    ) -> None:
        self.flushed_batches.append((tenant_id, stream_name, batch_id, records))


def test_storage_codec_round_trip_gzip() -> None:
    raw_payload = b"Hello, universal enterprise cloud storage platform!" * 50
    compressed = StorageCodec.compress(raw_payload, CompressionCodec.GZIP)
    assert len(compressed) < len(raw_payload)

    decompressed = StorageCodec.decompress(compressed, CompressionCodec.GZIP)
    assert decompressed == raw_payload


def test_storage_codec_round_trip_none() -> None:
    raw_payload = b"raw uncompressed bytes"
    compressed = StorageCodec.compress(raw_payload, CompressionCodec.NONE)
    assert compressed == raw_payload

    decompressed = StorageCodec.decompress(compressed, CompressionCodec.NONE)
    assert decompressed == raw_payload


def test_storage_codec_round_trip_zstd_or_fallback() -> None:
    raw_payload = b"Testing zstd compression with fallback safety" * 100
    compressed = StorageCodec.compress(raw_payload, CompressionCodec.ZSTD)
    assert len(compressed) < len(raw_payload)

    decompressed = StorageCodec.decompress(compressed, CompressionCodec.ZSTD)
    assert decompressed == raw_payload


def test_aioboto3_storage_partitioned_key_builder() -> None:
    storage = Aioboto3PayloadStorage(
        bucket="test-bucket",
        region="us-east-1",
    )
    key = storage.build_partitioned_key(
        tenant_id="logistics_corp",
        stream_name="telematics_stream",
        batch_id="bat_001",
        extension="raw",
        compression=CompressionCodec.GZIP,
    )
    assert key.startswith("tenants/logistics_corp/telematics_stream/")
    assert key.endswith("/bat_001.raw.gz")


@pytest.mark.asyncio
async def test_coalescer_eviction_on_count_threshold() -> None:
    flusher = CapturingFlusher()
    coalescer = MicroBatchCoalescer[DummyLogisticsPingDTO](
        tenant_id="tenant_alpha",
        stream_name="tms_pings",
        flusher=flusher,
        batch_size_threshold=3,
        max_window_seconds=10.0,
    )

    r1 = DummyLogisticsPingDTO("p1", "VIN100", 37.77, -122.41)
    r2 = DummyLogisticsPingDTO("p2", "VIN101", 37.78, -122.42)
    r3 = DummyLogisticsPingDTO("p3", "VIN102", 37.79, -122.43)

    f1 = await coalescer.push(r1)
    assert not f1
    assert coalescer.current_buffer_size == 1

    f2 = await coalescer.push(r2)
    assert not f2
    assert coalescer.current_buffer_size == 2

    # Pushing 3rd item hits batch_size_threshold=3 and triggers flush
    f3 = await coalescer.push(r3)
    assert f3
    assert coalescer.current_buffer_size == 0
    assert len(flusher.flushed_batches) == 1

    tenant_id, stream_name, batch_id, items = flusher.flushed_batches[0]
    assert tenant_id == "tenant_alpha"
    assert stream_name == "tms_pings"
    assert batch_id.startswith("bat_")
    assert len(items) == 3
    assert items[0].ping_id == "p1"
    assert items[2].ping_id == "p3"

    metrics = coalescer.get_metrics()
    assert metrics.total_flushes == 1
    assert metrics.total_records_flushed == 3


@pytest.mark.asyncio
async def test_coalescer_eviction_on_time_threshold() -> None:
    flusher = CapturingFlusher()
    coalescer = MicroBatchCoalescer[DummyLogisticsPingDTO](
        tenant_id="tenant_beta",
        stream_name="ad_clicks",
        flusher=flusher,
        batch_size_threshold=1000,
        max_window_seconds=0.05,  # 50ms window
    )

    r1 = DummyLogisticsPingDTO("click_1", "AD99", 0.0, 0.0)
    await coalescer.push(r1)
    assert len(flusher.flushed_batches) == 0

    # Wait past window
    await asyncio.sleep(0.06)

    flushed = await coalescer.flush_if_needed()
    assert flushed
    assert len(flusher.flushed_batches) == 1
    assert len(flusher.flushed_batches[0][3]) == 1


@pytest.mark.asyncio
async def test_coalescer_flush_all_manual_drain() -> None:
    flusher = CapturingFlusher()
    coalescer = MicroBatchCoalescer[DummyLogisticsPingDTO](
        tenant_id="tenant_gamma",
        stream_name="order_events",
        flusher=flusher,
        batch_size_threshold=5000,
        max_window_seconds=300.0,
    )

    items = [DummyLogisticsPingDTO(f"ord_{i}", f"SKU_{i}", 1.0, 2.0) for i in range(10)]
    await coalescer.push_many(items)
    assert len(flusher.flushed_batches) == 0

    flushed_count = await coalescer.flush_all()
    assert flushed_count == 10
    assert len(flusher.flushed_batches) == 1
    assert len(flusher.flushed_batches[0][3]) == 10
