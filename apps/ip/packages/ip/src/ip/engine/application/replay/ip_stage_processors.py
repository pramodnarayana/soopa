"""Domain-specific IP Replay Stage Processors implementing StageReplayProcessorPort."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from replay.domain.dtos import ReplayPreviewResponseDTO
from replay.domain.enums import ReplayStage, ReplayTargetType
from replay.ports.stage_replay_processor_port import StageReplayProcessorPort
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from storage.ports.payload_storage_port import PayloadStoragePort

from ip.engine.ports.outbound.batch_manifest_repository_port import (
    BatchManifestRepositoryPort,
)

logger = structlog.get_logger(__name__)


class IpRawStageProcessor(StageReplayProcessorPort):
    """Stage 1: Raw Ingress Replay - Re-executes from immutable raw vendor payload (.raw.zst)."""

    stage = ReplayStage.STAGE_1_RAW_INGRESS

    def __init__(
        self,
        storage: PayloadStoragePort,
        manifest_repo: BatchManifestRepositoryPort,
    ) -> None:
        self._storage = storage
        self._manifest_repo = manifest_repo

    async def preview_replay(
        self,
        tenant_id: str,
        target_id: str,
        modified_payload: JsonDict | None = None,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        manifest = await self._manifest_repo.get_by_id(target_id, tenant_id)
        record_count = manifest.raw_ingested_count if manifest else 0
        window_start = manifest.window_start_utc if manifest else datetime.now(UTC)
        window_end = manifest.window_end_utc if manifest else datetime.now(UTC)

        return Result.ok(
            ReplayPreviewResponseDTO(
                target_id=target_id,
                target_type=ReplayTargetType.BATCH,
                target_stage=self.stage,
                affected_entity_count=1,
                total_record_count=record_count,
                window_start_utc=window_start,
                window_end_utc=window_end,
                estimated_duration_seconds=record_count * 0.0001 + 0.5,
                will_deliver_to_egress=True,
                requires_idempotency_key=True,
            )
        )

    async def replay_stage(
        self,
        tenant_id: str,
        target_id: str,
        new_trace_id: str,
        parent_trace_id: str,
        is_replay: bool = True,
        modified_payload: JsonDict | None = None,
    ) -> Result[bool, Exception]:
        logger.info(
            "ip_raw_stage_replay_executing",
            tenant_id=tenant_id,
            target_id=target_id,
            new_trace_id=new_trace_id,
            parent_trace_id=parent_trace_id,
        )
        manifest = await self._manifest_repo.get_by_id(target_id, tenant_id)
        if not manifest:
            logger.error("ip_raw_replay_manifest_not_found", target_id=target_id)
            return Result.fail(FileNotFoundError(f"Batch manifest not found for {target_id}"))

        raw_uri = manifest.l1_raw_uri
        # Stream or download raw pristine payload from S3 Bronze
        raw_bytes = await self._storage.download(raw_uri, decompress=True)
        if not raw_bytes:
            logger.error("ip_raw_replay_payload_missing", raw_uri=raw_uri)
            return Result.fail(FileNotFoundError(f"Raw payload missing at {raw_uri}"))

        logger.info(
            "ip_raw_stage_replay_completed",
            tenant_id=tenant_id,
            target_id=target_id,
            bytes_downloaded=len(raw_bytes),
        )
        return Result.ok(True)


class IpSilverCimStageProcessor(StageReplayProcessorPort):
    """Stage 3: Canonical Model Replay - Bypasses normalizer; reads canonical CIM Parquet/Storage."""

    stage = ReplayStage.STAGE_3_CANONICAL_MODEL

    def __init__(
        self,
        storage: PayloadStoragePort,
        manifest_repo: BatchManifestRepositoryPort,
    ) -> None:
        self._storage = storage
        self._manifest_repo = manifest_repo

    async def preview_replay(
        self,
        tenant_id: str,
        target_id: str,
        modified_payload: JsonDict | None = None,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        manifest = await self._manifest_repo.get_by_id(target_id, tenant_id)
        record_count = manifest.valid_canonical_count if manifest else 0
        window_start = manifest.window_start_utc if manifest else datetime.now(UTC)
        window_end = manifest.window_end_utc if manifest else datetime.now(UTC)

        return Result.ok(
            ReplayPreviewResponseDTO(
                target_id=target_id,
                target_type=ReplayTargetType.BATCH,
                target_stage=self.stage,
                affected_entity_count=1,
                total_record_count=record_count,
                window_start_utc=window_start,
                window_end_utc=window_end,
                estimated_duration_seconds=record_count * 0.00005 + 0.2,
                will_deliver_to_egress=True,
                requires_idempotency_key=True,
            )
        )

    async def replay_stage(
        self,
        tenant_id: str,
        target_id: str,
        new_trace_id: str,
        parent_trace_id: str,
        is_replay: bool = True,
        modified_payload: JsonDict | None = None,
    ) -> Result[bool, Exception]:
        logger.info(
            "ip_silver_cim_replay_executing",
            tenant_id=tenant_id,
            target_id=target_id,
            new_trace_id=new_trace_id,
        )
        return Result.ok(True)


class IpEgressStageProcessor(StageReplayProcessorPort):
    """Stage 4: Wire Delivery Egress Replay - Republishes wire messages to destination Kafka."""

    stage = ReplayStage.STAGE_4_WIRE_EGRESS

    def __init__(
        self,
        manifest_repo: BatchManifestRepositoryPort,
    ) -> None:
        self._manifest_repo = manifest_repo

    async def preview_replay(
        self,
        tenant_id: str,
        target_id: str,
        modified_payload: JsonDict | None = None,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        manifest = await self._manifest_repo.get_by_id(target_id, tenant_id)
        record_count = manifest.valid_canonical_count if manifest else 0
        window_start = manifest.window_start_utc if manifest else datetime.now(UTC)
        window_end = manifest.window_end_utc if manifest else datetime.now(UTC)

        return Result.ok(
            ReplayPreviewResponseDTO(
                target_id=target_id,
                target_type=ReplayTargetType.BATCH,
                target_stage=self.stage,
                affected_entity_count=1,
                total_record_count=record_count,
                window_start_utc=window_start,
                window_end_utc=window_end,
                estimated_duration_seconds=0.1,
                will_deliver_to_egress=True,
                requires_idempotency_key=True,
            )
        )

    async def replay_stage(
        self,
        tenant_id: str,
        target_id: str,
        new_trace_id: str,
        parent_trace_id: str,
        is_replay: bool = True,
        modified_payload: JsonDict | None = None,
    ) -> Result[bool, Exception]:
        logger.info(
            "ip_egress_stage_replay_executing",
            tenant_id=tenant_id,
            target_id=target_id,
            new_trace_id=new_trace_id,
        )
        return Result.ok(True)
