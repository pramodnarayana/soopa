"""Use case for modifying an Ingest or Stitch payload and replaying the stage trace with full lineage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from seedwork.domain.types import JsonDict

from ip.engine.application.use_cases.replay.replay_stage_use_case import (
    ReplayStage,
    ReplayStageCommand,
    ReplayStageResultDTO,
    ReplayStageUseCase,
    resolve_replay_stages,
)
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import (
    InvalidReplayPayloadError,
    IpError,
    ReplayStageNotAvailableError,
    Result,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort


@dataclass(frozen=True, kw_only=True)
class ModifyAndReplayCommand:
    """Command to override a record's payload at Ingest or Stitch stage and trigger a new replay trace."""

    tenant_id: str
    trace_id: str
    stage: PipelineStage | ReplayStage
    modified_payload: JsonDict
    actor: str = "SYSTEM"


class ModifyAndReplayUseCase:
    """Validates payload override constraints and delegates replay execution to ReplayStageUseCase."""

    def __init__(
        self,
        uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stage_processors: Mapping[PipelineStage, StageReplayProcessorPort],
    ) -> None:
        self._replay_use_case = ReplayStageUseCase(
            uow_provider=uow_provider,
            stage_processors=stage_processors,
        )

    async def execute(
        self, command: ModifyAndReplayCommand
    ) -> Result[ReplayStageResultDTO, IpError]:
        if not command.modified_payload:
            return Result.err(
                InvalidReplayPayloadError.for_trace(
                    command.trace_id,
                    "Modified replay payload must be a non-empty JSON object.",
                )
            )

        stage_res = resolve_replay_stages(command.stage, command.trace_id)
        if stage_res.is_err:
            return Result.err(stage_res.unwrap_err())
        _, replay_stage = stage_res.unwrap()

        if replay_stage not in (ReplayStage.RETRY_INGEST, ReplayStage.RETRY_STITCH):
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    replay_stage.value,
                    f"Modify-and-replay is supported only for RETRY_INGEST and RETRY_STITCH (got '{replay_stage.value}').",
                )
            )

        return await self._replay_use_case.execute(
            ReplayStageCommand(
                tenant_id=command.tenant_id,
                trace_id=command.trace_id,
                stage=replay_stage,
                actor=command.actor,
                modified_payload=command.modified_payload,
            )
        )


__all__ = ["ModifyAndReplayCommand", "ModifyAndReplayUseCase"]
