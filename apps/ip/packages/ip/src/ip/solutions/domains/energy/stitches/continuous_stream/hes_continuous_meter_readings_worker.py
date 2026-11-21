"""Continuous Stream Dual-Path Worker: Fast-Path Wire Egress (<200ms) + Micro-Batch Coalesced Storage."""

from __future__ import annotations

import json
from collections.abc import Sequence

import structlog
from database.olap.ports.olap_client_port import OlapClientPort
from pubsub.ports.message_publisher_port import MessagePublisherPort
from seedwork.domain.types import JsonValue
from storage.coalescer.micro_batch_coalescer import MicroBatchCoalescer
from storage.coalescer.ports import BatchFlusherPort
from storage.domain.enums import CompressionCodec
from storage.ports.payload_storage_port import PayloadStoragePort

from ip.solutions.domains.energy.canonical import CanonicalMeterReadingDTO

logger = structlog.get_logger(__name__)


class EnergyOlapFlusher(BatchFlusherPort[CanonicalMeterReadingDTO]):
    """Flushes coalesced meter reading batches to S3 Silver storage and ClickHouse OLAP."""

    def __init__(
        self,
        storage: PayloadStoragePort,
        olap_client: OlapClientPort,
    ) -> None:
        self._storage = storage
        self._olap_client = olap_client

    async def flush_batch(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        records: tuple[CanonicalMeterReadingDTO, ...],
    ) -> None:
        if not records:
            return

        # 1. Upload to S3 Silver (.silver.json.gz or parquet)
        silver_data = [
            {
                "tenant_id": r.tenant_id,
                "meter_serial_number": r.meter_serial_number,
                "service_point_id": r.service_point_id,
                "interval_end_utc": r.interval_end_utc.isoformat(),
                "kwh_delivered": r.kwh_delivered,
                "kwh_received": r.kwh_received,
                "voltage_avg": r.voltage_avg,
                "quality_flags": [q.value for q in r.quality_flags],
            }
            for r in records
        ]
        silver_bytes = json.dumps(silver_data).encode("utf-8")
        await self._storage.upload_partitioned(
            tenant_id=tenant_id,
            stream_name=stream_name,
            batch_id=batch_id,
            payload=silver_bytes,
            extension="silver.json",
            compression=CompressionCodec.GZIP,
        )

        # 2. Insert into ClickHouse OLAP (ip.meter_readings)
        clickhouse_records: list[dict[str, JsonValue]] = [
            {
                "tenant_id": r.tenant_id,
                "meter_serial_number": r.meter_serial_number,
                "interval_end_utc": r.interval_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "service_point_id": r.service_point_id or "",
                "connection_id": "conn_continuous",
                "batch_id": batch_id,
                "scaled_kwh_delivered": r.kwh_delivered,
                "scaled_kwh_received": r.kwh_received,
                "voltage_v": r.voltage_avg,
                "quality_status": "VALID",
                "parquet_row_offset": idx,
                "trace_id": f"trc_{batch_id}_{idx}",
                "correlation_id": batch_id,
            }
            for idx, r in enumerate(records)
        ]
        await self._olap_client.insert_batch("ip.meter_readings", clickhouse_records)


class HesContinuousMeterReadingsWorker:
    """Orchestrates Dual-Path continuous ingestion for AMI meter reading streams."""

    def __init__(
        self,
        tenant_id: str,
        storage: PayloadStoragePort,
        olap_client: OlapClientPort,
        publisher: MessagePublisherPort,
        egress_topic: str = "mdm.meter_readings.inbound",
        batch_size_threshold: int = 25_000,
        max_window_seconds: float = 60.0,
    ) -> None:
        self.tenant_id = tenant_id
        self._publisher = publisher
        self._egress_topic = egress_topic

        flusher = EnergyOlapFlusher(storage, olap_client)
        self._coalescer = MicroBatchCoalescer[CanonicalMeterReadingDTO](
            tenant_id=tenant_id,
            stream_name="meter_readings_continuous",
            flusher=flusher,
            batch_size_threshold=batch_size_threshold,
            max_window_seconds=max_window_seconds,
        )

    async def ingest_reading(self, reading: CanonicalMeterReadingDTO) -> None:
        """Executes Dual-Path Ingestion: Fast-Path Wire Egress + Micro-Batch Storage Coalescer."""
        # 1. Fast-Path Wire Delivery (< 200ms)
        wire_payload = json.dumps(
            {
                "tenantId": reading.tenant_id,
                "meterId": reading.meter_serial_number,
                "timestamp": reading.interval_end_utc.isoformat(),
                "kwhDelivered": reading.kwh_delivered,
                "kwhReceived": reading.kwh_received,
                "voltage": reading.voltage_avg,
            }
        ).encode("utf-8")

        await self._publisher.publish(
            destination_uri=f"kafka://{self._egress_topic}",
            message=wire_payload,
            key=reading.meter_serial_number.encode("utf-8"),
        )

        # 2. Slow-Path Micro-Batch Buffering (Parquet + ClickHouse)
        await self._coalescer.push(reading)

    async def ingest_batch(self, readings: Sequence[CanonicalMeterReadingDTO]) -> None:
        for r in readings:
            await self.ingest_reading(r)

    async def drain_all(self) -> int:
        return await self._coalescer.flush_all()
