"""Universal Replay Coordinator implementation (core/platform/packages/replay)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from replay.domain.dtos import (
    ExecuteReplayCommandDTO,
    ReplayExecutionResultDTO,
    ReplayPreviewRequestDTO,
    ReplayPreviewResponseDTO,
)
from replay.domain.enums import ReplayStage, ReplayStatus
from replay.domain.exceptions import UnsupportedReplayStageError
from replay.ports.replay_coordinator_port import ReplayCoordinatorPort
from replay.ports.stage_replay_processor_port import StageReplayProcessorPort
from seedwork.domain.exceptions import Result
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


class UniversalReplayCoordinator(ReplayCoordinatorPort):
    """Universal coordinator that orchestrates multi-stage replays across pluggable domain processors."""

    def __init__(self) -> None:
        self._processors: dict[ReplayStage, StageReplayProcessorPort] = {}

    def register_processor(self, processor: StageReplayProcessorPort) -> None:
        self._processors[processor.stage] = processor
        logger.info("replay_processor_registered", stage=processor.stage.value)

    async def preview(
        self,
        request: ReplayPreviewRequestDTO,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        processor = self._processors.get(request.target_stage)
        if not processor:
            logger.error("replay_preview_stage_unsupported", stage=request.target_stage.value)
            return Result.fail(UnsupportedReplayStageError(request.target_stage.value))

        logger.info(
            "replay_preview_calculating",
            tenant_id=request.tenant_id,
            target_id=request.target_id,
            target_type=request.target_type.value,
            stage=request.target_stage.value,
        )
        return await processor.preview_replay(
            tenant_id=request.tenant_id,
            target_id=request.target_id,
            modified_payload=request.modified_payload,
        )

    async def execute(
        self,
        command: ExecuteReplayCommandDTO,
    ) -> Result[ReplayExecutionResultDTO, Exception]:
        processor = self._processors.get(command.target_stage)
        if not processor:
            logger.error("replay_execute_stage_unsupported", stage=command.target_stage.value)
            return Result.fail(UnsupportedReplayStageError(command.target_stage.value))

        replay_id = generate_id("rpl")
        trace_id = generate_id("trc")
        parent_trace_id = f"parent_{command.target_id}"

        logger.info(
            "replay_execution_initiated",
            replay_id=replay_id,
            tenant_id=command.tenant_id,
            target_id=command.target_id,
            target_type=command.target_type.value,
            stage=command.target_stage.value,
            actor=command.actor,
            trace_id=trace_id,
            idempotency_key=command.idempotency_key,
        )

        replay_res = await processor.replay_stage(
            tenant_id=command.tenant_id,
            target_id=command.target_id,
            new_trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            is_replay=True,
            modified_payload=command.payload_override,
        )

        if replay_res.is_err:
            logger.error(
                "replay_execution_failed",
                replay_id=replay_id,
                target_id=command.target_id,
                error=str(replay_res.error),
            )
            err = (
                replay_res.error
                if replay_res.error is not None
                else Exception("Unknown replay error")
            )
            return Result.fail(err)

        result_dto = ReplayExecutionResultDTO(
            replay_id=replay_id,
            target_id=command.target_id,
            target_type=command.target_type,
            trace_id=trace_id,
            target_stage=command.target_stage,
            status=ReplayStatus.IN_FLIGHT,
            initiated_at_utc=datetime.now(UTC),
        )
        return Result.ok(result_dto)
