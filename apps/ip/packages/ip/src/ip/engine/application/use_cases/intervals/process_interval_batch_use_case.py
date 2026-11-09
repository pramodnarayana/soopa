"""L2/L3/L4 vectorized batch normalization and storm-safe promotion use case for interval streams."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

import structlog

from ip.engine.domain.exceptions import (
    IntervalBatchNotFoundError,
    IpError,
    Result,
)
from ip.engine.domain.intervals.enums import BatchManifestStatus
from ip.engine.domain.intervals.models import (
    BatchManifest,
    BatchReconciliationCounts,
    FeederOutageCluster,
    StormAggregationPolicy,
    VeeValidationPolicy,
)
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap
from ip.engine.ports.outbound.columnar_batch_processor_port import ColumnarBatchProcessorPort
from ip.engine.ports.outbound.interval_rollup_repository_port import IntervalRollupRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessIntervalBatchCommand:
    """Command to execute vectorized L2/L3 normalization and L4 rollup commit for a buffered batch."""

    tenant_id: str
    batch_id: str
    storm_policy: StormAggregationPolicy | None = None
    vee_policy: VeeValidationPolicy | None = None
    delivery_receipt_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessIntervalBatchResponse:
    """Response returned upon completing vectorized normalization and Zero-Loss reconciliation."""

    batch_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    status: BatchManifestStatus
    counts: BatchReconciliationCounts
    promoted_outage_clusters: tuple[FeederOutageCluster, ...]
    l2_replica_uri: str | None
    l3_canonical_uri: str | None
    trace_id: str
    is_already_processed: bool = False


_BATCH_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_BATCH_LOCKS_GUARD = asyncio.Lock()


async def _get_manifest_lock(tenant_id: str, batch_id: str) -> asyncio.Lock:
    key = (tenant_id, batch_id)
    async with _BATCH_LOCKS_GUARD:
        lock = _BATCH_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _BATCH_LOCKS[key] = lock
        return lock


class ProcessIntervalBatchUseCase:
    """Executes vectorized columnar normalization, zero-copy rollup store ingestion, and storm promotion."""

    def __init__(
        self,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        storage: TieredStoragePort,
        columnar_processor: ColumnarBatchProcessorPort,
        rollup_repository: IntervalRollupRepositoryPort,
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._storage = storage
        self._columnar_processor = columnar_processor
        self._rollup_repository = rollup_repository

    async def _load_gem_crosswalk(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        tenant_id: str,
        connection_id: str,
    ) -> Mapping[str, str]:
        gem_entries: list[GlobalEntityMap] = []
        page_limit = 1000
        current_offset = 0
        while True:
            page = await uow.entity_maps.list_entries(
                tenant_id,
                source_connection_id=connection_id,
                limit=page_limit,
                offset=current_offset,
            )
            if not page:
                break
            gem_entries.extend(page)
            if len(page) < page_limit:
                break
            current_offset += len(page)
        return {entry.source_entity_id: entry.canonical_id for entry in gem_entries}

    async def _fail_manifest(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        manifest: BatchManifest,
        error_message: str,
        bound_log: structlog.stdlib.BoundLogger,
        event_name: str,
    ) -> None:
        manifest.mark_failed(error_message)
        await uow.batch_manifests.save(manifest)
        await uow.commit()
        bound_log.error(event_name, reason=error_message)

    async def execute(
        self,
        command: ProcessIntervalBatchCommand,
    ) -> Result[ProcessIntervalBatchResponse, IpError]:
        bound_log = logger.bind(
            tenant_id=command.tenant_id,
            batch_id=command.batch_id,
        )

        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            bound_log.error("interval_process_shard_not_found")
            return Result.fail(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        # Coordinate manifest processing across HTTP and worker to prevent race conditions
        manifest_lock = await _get_manifest_lock(command.tenant_id, command.batch_id)
        async with (
            manifest_lock,
            self._dp_uow_provider.get_data_plane_uow(command.tenant_id, shard_id, shard_dsn) as uow,
        ):
            manifest = await uow.batch_manifests.get_by_id(command.batch_id, command.tenant_id)
            if manifest is None:
                bound_log.error("interval_batch_manifest_not_found")
                return Result.fail(IntervalBatchNotFoundError.for_batch(command.batch_id))

            if manifest.status is BatchManifestStatus.COMPLETED:
                bound_log.info("interval_batch_already_completed")
                return Result.ok(
                    ProcessIntervalBatchResponse(
                        batch_id=manifest.id,
                        tenant_id=manifest.tenant_id,
                        connection_id=manifest.connection_id,
                        stream_name=manifest.stream_name,
                        status=manifest.status,
                        counts=manifest.reconciliation_counts,
                        promoted_outage_clusters=(),
                        l2_replica_uri=manifest.l2_replica_uri,
                        l3_canonical_uri=manifest.l3_canonical_uri,
                        trace_id=manifest.trace_id,
                        is_already_processed=True,
                    )
                )

            manifest.mark_processing()
            is_inlined = manifest.inline_payload is not None
            s3_key = (
                manifest.l1_raw_uri.removeprefix("s3://")
                if manifest.l1_raw_uri.startswith("s3://")
                else None
            )
            storage_dto = TieredStorageResultDTO(
                is_inlined=is_inlined,
                raw_payload=manifest.inline_payload,
                s3_key=s3_key,
                payload_size_bytes=manifest.payload_size_bytes,
                payload_sha256=manifest.payload_sha256,
            )

            raw_bytes_res = await self._storage.retrieve(storage_dto)
            if raw_bytes_res.is_err:
                raw_err = raw_bytes_res.unwrap_err()
                await self._fail_manifest(
                    uow,
                    manifest,
                    raw_err.message,
                    bound_log,
                    "interval_batch_payload_retrieval_failed",
                )
                return Result.fail(raw_err)

            gem_crosswalk = await self._load_gem_crosswalk(
                uow, command.tenant_id, manifest.connection_id
            )

            norm_res = self._columnar_processor.normalize_batch(
                batch_id=manifest.id,
                tenant_id=manifest.tenant_id,
                connection_id=manifest.connection_id,
                stream_name=manifest.stream_name,
                trace_id=manifest.trace_id,
                raw_payload_bytes=raw_bytes_res.unwrap(),
                payload_format=manifest.payload_format,
                gem_crosswalk=gem_crosswalk,
                storm_policy=command.storm_policy,
                vee_policy=command.vee_policy,
            )
            if norm_res.is_err:
                norm_err = norm_res.unwrap_err()
                await self._fail_manifest(
                    uow,
                    manifest,
                    norm_err.message,
                    bound_log,
                    "interval_batch_normalization_failed",
                )
                return Result.fail(norm_err)

            normalized = norm_res.unwrap()

            # Invariant 1: Stream contiguous columnar binary buffer directly to Rollup Repository
            insert_res = await self._rollup_repository.insert_columnar_batch(
                tenant_id=manifest.tenant_id,
                batch_id=manifest.id,
                stream_name=manifest.stream_name,
                columnar_bytes=normalized.columnar_bytes,
            )
            if insert_res.is_err:
                insert_err = insert_res.unwrap_err()
                await self._fail_manifest(
                    uow,
                    manifest,
                    insert_err.message,
                    bound_log,
                    "interval_rollup_insert_failed",
                )
                return Result.fail(insert_err)

            if command.delivery_receipt_id is not None:
                receipt_res = await self._rollup_repository.record_delivery_receipt(
                    tenant_id=manifest.tenant_id,
                    batch_id=manifest.id,
                    delivery_receipt_id=command.delivery_receipt_id,
                )
                if receipt_res.is_err:
                    receipt_err = receipt_res.unwrap_err()
                    await self._fail_manifest(
                        uow,
                        manifest,
                        receipt_err.message,
                        bound_log,
                        "interval_delivery_receipt_update_failed",
                    )
                    return Result.fail(receipt_err)

            l2_uri = f"columnar://l2_replica/{manifest.tenant_id}/{manifest.id}.columnar"
            l3_uri = f"columnar://l3_canonical/{manifest.tenant_id}/{manifest.id}.columnar"

            # Promote storm-grouped 0.0V feeder outage clusters to P0_CRITICAL real-time lane
            manifest.promote_outage_clusters(normalized.outage_clusters)

            # Enforce Zero-Loss Accounting Equation before marking COMPLETED
            reconcile_res = manifest.complete_reconciled(
                counts=normalized.counts,
                l2_replica_uri=l2_uri,
                l3_canonical_uri=l3_uri,
                delivery_receipt_id=command.delivery_receipt_id,
            )
            if reconcile_res.is_err:
                reconcile_err = reconcile_res.unwrap_err()
                await self._fail_manifest(
                    uow,
                    manifest,
                    reconcile_err.message,
                    bound_log,
                    "interval_reconciliation_imbalance",
                )
                return Result.fail(reconcile_err)

            await uow.batch_manifests.save(manifest)
            await uow.commit()

        bound_log.info(
            "interval_batch_processed",
            trace_id=manifest.trace_id,
            raw_ingested=normalized.counts.raw_ingested,
            valid_canonical=normalized.counts.valid_canonical,
            duplicates_dropped=normalized.counts.duplicates_dropped,
            quarantined_held=normalized.counts.quarantined_held,
            promoted_outage_clusters=len(normalized.outage_clusters),
        )
        return Result.ok(
            ProcessIntervalBatchResponse(
                batch_id=manifest.id,
                tenant_id=manifest.tenant_id,
                connection_id=manifest.connection_id,
                stream_name=manifest.stream_name,
                status=manifest.status,
                counts=normalized.counts,
                promoted_outage_clusters=normalized.outage_clusters,
                l2_replica_uri=l2_uri,
                l3_canonical_uri=l3_uri,
                trace_id=manifest.trace_id,
                is_already_processed=False,
            )
        )


__all__ = [
    "ProcessIntervalBatchCommand",
    "ProcessIntervalBatchResponse",
    "ProcessIntervalBatchUseCase",
]
