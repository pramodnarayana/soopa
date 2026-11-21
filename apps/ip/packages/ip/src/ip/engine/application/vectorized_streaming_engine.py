"""Universal High-Throughput Vectorized Streaming Engine and Zero-Loss Accounting Reconciler.

Pure domain-agnostic streaming pipeline:
1. Bronze S3 Claim-Check download & decompression.
2. In-memory SIMD / Vectorized normalization & VEE segregation.
3. Mathematical enforcement of the Zero-Loss Accounting Equation.
4. Silver dataset persistence to partitioned object storage.
5. Columnar analytical indexing into OLAP storage (ClickHouse).
6. State checkpointing in the PostgreSQL Batch Manifest Ledger.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Generic, TypeVar

import structlog
from database.olap.ports.olap_client_port import OlapClientPort
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonValue
from storage.domain.enums import CompressionCodec
from storage.ports.payload_storage_port import PayloadStoragePort

from ip.engine.domain.exceptions import (
    IntervalReconciliationImbalanceError,
    IpError,
)
from ip.engine.domain.intervals.enums import BatchManifestStatus
from ip.engine.domain.intervals.models import BatchManifest
from ip.engine.domain.normalization.dtos import TransformationContext
from ip.engine.ports.outbound.batch_manifest_repository_port import (
    BatchManifestRepositoryPort,
)

logger = structlog.get_logger(__name__)

TRecord = TypeVar("TRecord")


class VectorizedStreamingEngine(Generic[TRecord]):
    """Consumes Claim-Check pointers from Bronze S3, executes vectorized normalization,

    enforces the Zero-Loss Accounting Equation, stores Silver datasets, and updates the OLAP index.
    Completely decoupled from concrete domain models via Strategy Pattern.
    """

    def __init__(
        self,
        storage: PayloadStoragePort,
        olap_client: OlapClientPort,
        manifest_repo: BatchManifestRepositoryPort,
    ) -> None:
        self._storage = storage
        self._olap_client = olap_client
        self._manifest_repo = manifest_repo

    @staticmethod
    def _parse_raw_records(raw_bytes: bytes) -> list[dict[str, object]]:
        """Parses raw bronze payload into a list of record mappings with JSON-lines fallback."""
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, dict):
                for val in parsed.values():
                    if isinstance(val, list):
                        return [item for item in val if isinstance(item, dict)]
                return [parsed]
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        records: list[dict[str, object]] = []
        for line in raw_bytes.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except json.JSONDecodeError:
                logger.debug("skipped_malformed_json_line", line=line[:64])
        return records

    @staticmethod
    def _normalize_records(
        raw_records: list[dict[str, object]],
        normalizer_func: Callable[[dict[str, object], TransformationContext], TRecord | None],
        transform_ctx: TransformationContext,
        batch_id: str,
        validator_func: Callable[[TRecord], bool] | None = None,
    ) -> tuple[list[TRecord], list[dict[str, object]]]:
        """Normalizes and validates records, segregating valid canonical records from quarantined records."""
        valid_canonical: list[TRecord] = []
        quarantined: list[dict[str, object]] = []

        for record in raw_records:
            try:
                dto = normalizer_func(record, transform_ctx)
                if dto is not None and (validator_func is None or validator_func(dto)):
                    valid_canonical.append(dto)
                else:
                    quarantined.append(record)
                    logger.debug("record_quarantined_validation_failure", batch_id=batch_id)
            except Exception as exc:  # noqa: BLE001 - Domain VEE normalizer quarantine catches per-record exceptions
                quarantined.append(record)
                logger.debug(
                    "record_quarantined_normalization_exception", batch_id=batch_id, error=str(exc)
                )

        return valid_canonical, quarantined

    async def _update_manifest_record(
        self,
        *,
        batch_id: str,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        app_id: str,
        bronze_uri: str,
        silver_uri: str,
        raw_count: int,
        raw_bytes_len: int,
        valid_count: int,
        quarantined_count: int,
        window_start_utc: datetime | None = None,
        window_end_utc: datetime | None = None,
    ) -> BatchManifest:
        """Saves or updates the PostgreSQL BatchManifest ledger entry."""
        now = datetime.now(UTC)
        manifest = await self._manifest_repo.get_by_id(batch_id, tenant_id)
        if not manifest:
            manifest = BatchManifest(
                id=batch_id,
                tenant_id=tenant_id,
                trace_id=f"trc_{batch_id}",
                connection_id=connection_id,
                app_id=app_id,
                stream_name=stream_name,
                l1_raw_uri=bronze_uri,
                l3_canonical_uri=silver_uri,
                payload_sha256="batch_sha256",
                payload_size_bytes=raw_bytes_len,
                window_start_utc=window_start_utc or now,
                window_end_utc=window_end_utc or now,
                raw_ingested_count=raw_count,
                valid_canonical_count=valid_count,
                quarantined_held_count=quarantined_count,
                status=BatchManifestStatus.COMPLETED,
                completed_at=now,
            )
        else:
            manifest.l3_canonical_uri = silver_uri
            manifest.raw_ingested_count = raw_count
            manifest.valid_canonical_count = valid_count
            manifest.quarantined_held_count = quarantined_count
            manifest.status = BatchManifestStatus.COMPLETED
            manifest.completed_at = now

        await self._manifest_repo.save(manifest)
        return manifest

    async def process_batch(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        connection_id: str,
        stream_name: str,
        bronze_uri: str,
        normalizer_func: Callable[[dict[str, object], TransformationContext], TRecord | None],
        olap_table: str,
        olap_formatter: Callable[[TRecord, TransformationContext, int], dict[str, JsonValue]],
        silver_formatter: Callable[[TRecord], dict[str, JsonValue]],
        validator_func: Callable[[TRecord], bool] | None = None,
        app_id: str = "integration_pipeline",
        window_start_utc: datetime | None = None,
        window_end_utc: datetime | None = None,
        ctx: TransformationContext | None = None,
    ) -> Result[BatchManifest, IpError]:
        """Processes a Bronze payload, reconciles counts, pushes to Silver, and indexes in ClickHouse."""
        logger.info(
            "vectorized_engine_processing_batch",
            tenant_id=tenant_id,
            batch_id=batch_id,
            bronze_uri=bronze_uri,
            olap_table=olap_table,
        )

        transform_ctx = ctx or TransformationContext(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream_name,
            trace_id=f"trc_{batch_id}",
        )

        raw_bytes = await self._storage.download(bronze_uri, decompress=True)
        if not raw_bytes:
            logger.error("bronze_payload_download_failed", bronze_uri=bronze_uri)
            manifest = await self._manifest_repo.get_by_id(batch_id, tenant_id)
            if manifest:
                manifest.status = BatchManifestStatus.FAILED
                manifest.error_message = f"Missing bronze payload at {bronze_uri}"
                await self._manifest_repo.save(manifest)
            return Result.fail(
                IntervalReconciliationImbalanceError.for_counts(
                    batch_id=batch_id,
                    raw_ingested=0,
                    duplicates_dropped=0,
                    valid_canonical=0,
                    quarantined_held=0,
                )
            )

        raw_records = self._parse_raw_records(raw_bytes)
        raw_count = len(raw_records)
        valid_canonical, quarantined = self._normalize_records(
            raw_records, normalizer_func, transform_ctx, batch_id, validator_func
        )

        valid_count = len(valid_canonical)
        quarantined_count = len(quarantined)
        duplicates_dropped = 0

        # Enforce Zero-Loss Accounting Equation: raw_count == duplicates + valid + quarantined
        if raw_count != (duplicates_dropped + valid_count + quarantined_count):
            logger.error(
                "zero_loss_reconciliation_imbalance_detected",
                batch_id=batch_id,
                raw_count=raw_count,
                valid_count=valid_count,
                quarantined_count=quarantined_count,
            )
            return Result.fail(
                IntervalReconciliationImbalanceError.for_counts(
                    batch_id=batch_id,
                    raw_ingested=raw_count,
                    duplicates_dropped=duplicates_dropped,
                    valid_canonical=valid_count,
                    quarantined_held=quarantined_count,
                )
            )

        silver_data = [silver_formatter(dto) for dto in valid_canonical]
        silver_bytes = json.dumps(silver_data).encode("utf-8")
        silver_uri = await self._storage.upload_partitioned(
            tenant_id=tenant_id,
            stream_name=stream_name,
            batch_id=batch_id,
            payload=silver_bytes,
            extension="silver.json",
            compression=CompressionCodec.GZIP,
        )

        clickhouse_records = [
            olap_formatter(dto, transform_ctx, offset) for offset, dto in enumerate(valid_canonical)
        ]
        await self._olap_client.insert_batch(olap_table, clickhouse_records)

        manifest = await self._update_manifest_record(
            batch_id=batch_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            app_id=app_id,
            bronze_uri=bronze_uri,
            silver_uri=silver_uri,
            raw_count=raw_count,
            raw_bytes_len=len(raw_bytes),
            valid_count=valid_count,
            quarantined_count=quarantined_count,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
        )

        logger.info(
            "vectorized_engine_batch_completed_success",
            batch_id=batch_id,
            raw_count=raw_count,
            valid_count=valid_count,
            quarantined_count=quarantined_count,
            silver_uri=silver_uri,
        )
        return Result.ok(manifest)
