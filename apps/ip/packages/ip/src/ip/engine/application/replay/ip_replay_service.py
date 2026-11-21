"""Application Service coordinating IP domain replay workflows and audit ledger."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from replay.application.replay_coordinator import UniversalReplayCoordinator
from replay.domain.dtos import (
    ExecuteReplayCommandDTO,
    ReplayExecutionResultDTO,
    ReplayPreviewRequestDTO,
    ReplayPreviewResponseDTO,
)
from seedwork.domain.exceptions import Result
from storage.ports.payload_storage_port import PayloadStoragePort

from ip.engine.application.replay.ip_stage_processors import (
    IpEgressStageProcessor,
    IpRawStageProcessor,
    IpSilverCimStageProcessor,
)
from ip.engine.domain.replay.models import IpReplayLedgerRecord
from ip.engine.domain.replay.ports import IpReplayLedgerRepositoryPort
from ip.engine.ports.outbound.batch_manifest_repository_port import (
    BatchManifestRepositoryPort,
)

logger = structlog.get_logger(__name__)


class IpReplayApplicationService:
    """Manages Replay Preview and Execution for the Soopa Integration Platform (apps/ip)."""

    def __init__(
        self,
        storage: PayloadStoragePort,
        manifest_repo: BatchManifestRepositoryPort,
        ledger_repo: IpReplayLedgerRepositoryPort,
        coordinator: UniversalReplayCoordinator | None = None,
    ) -> None:
        self._ledger_repo = ledger_repo
        self._coordinator = coordinator or UniversalReplayCoordinator()

        # Register IP domain stage processors
        self._coordinator.register_processor(IpRawStageProcessor(storage, manifest_repo))
        self._coordinator.register_processor(IpSilverCimStageProcessor(storage, manifest_repo))
        self._coordinator.register_processor(IpEgressStageProcessor(manifest_repo))

    async def preview_replay(
        self,
        request: ReplayPreviewRequestDTO,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        """Evaluates side-effects and boundaries of a proposed replay."""
        return await self._coordinator.preview(request)

    async def execute_replay(
        self,
        command: ExecuteReplayCommandDTO,
    ) -> Result[ReplayExecutionResultDTO, Exception]:
        """Executes a replay and records audit history in ip.ip_replay_ledger atomically."""
        logger.info(
            "ip_replay_service_initiating",
            tenant_id=command.tenant_id,
            target_id=command.target_id,
            target_type=command.target_type.value,
            stage=command.target_stage.value,
            actor=command.actor,
            idempotency_key=command.idempotency_key,
        )

        # 1. Atomic Idempotency Check: if identical idempotency_key already recorded, return existing execution
        existing_record = await self._ledger_repo.get_by_idempotency_key(
            tenant_id=command.tenant_id,
            idempotency_key=command.idempotency_key,
        )
        if existing_record is not None:
            logger.info(
                "ip_replay_service_idempotency_deduplicated",
                tenant_id=command.tenant_id,
                idempotency_key=command.idempotency_key,
                replay_id=existing_record.id,
                status=existing_record.status.value,
            )
            return Result.ok(
                ReplayExecutionResultDTO(
                    replay_id=existing_record.id,
                    target_id=existing_record.target_id,
                    target_type=existing_record.target_type,
                    trace_id=existing_record.trace_id,
                    target_stage=existing_record.target_stage,
                    status=existing_record.status,
                    initiated_at_utc=existing_record.created_at,
                )
            )

        # 2. Execute via Universal Replay Coordinator
        exec_res = await self._coordinator.execute(command)
        if exec_res.is_err:
            ledger_rec = IpReplayLedgerRecord.create(
                tenant_id=command.tenant_id,
                idempotency_key=command.idempotency_key,
                target_type=command.target_type,
                target_id=command.target_id,
                target_stage=command.target_stage,
                trace_id="failed_init",
                parent_trace_id=f"parent_{command.target_id}",
                original_trace_id=command.original_trace_id,
                correlation_id=command.correlation_id,
                actor=command.actor,
                reason=command.reason,
                payload_override=command.payload_override,
                affected_records=0,
            )
            ledger_rec.mark_failed(str(exec_res.error))
            await self._ledger_repo.save(ledger_rec)
            return exec_res

        result_dto = exec_res.unwrap()
        ledger_rec = IpReplayLedgerRecord(
            id=result_dto.replay_id,
            tenant_id=command.tenant_id,
            idempotency_key=command.idempotency_key,
            target_type=command.target_type,
            target_id=command.target_id,
            target_stage=command.target_stage,
            trace_id=result_dto.trace_id,
            parent_trace_id=f"parent_{command.target_id}",
            original_trace_id=command.original_trace_id,
            correlation_id=command.correlation_id,
            actor=command.actor,
            reason=command.reason,
            payload_override=command.payload_override,
            affected_records=0,
            status=result_dto.status,
            error_message=None,
            created_at=datetime.now(UTC),
            completed_at=None,
        )
        ledger_rec.mark_completed()
        await self._ledger_repo.save(ledger_rec)

        return Result.ok(result_dto)
