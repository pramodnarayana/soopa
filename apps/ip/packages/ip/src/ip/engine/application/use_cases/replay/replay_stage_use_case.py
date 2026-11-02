"""Use case for deterministic polymorphic stage replay via StageReplayProcessorPort."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import structlog
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id

from ip.engine.application.use_cases.replay.stage_replay_processor import (
    StageReplayProcessorPort,
    StageReplayRequest,
)
from ip.engine.application.use_cases.trace.get_ip_trace_use_case import GetIpTraceUseCase
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import (
    IpError,
    ReplayStageNotAvailableError,
    Result,
    TraceNotFoundError,
)
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


class ReplayStage(StrEnum):
    """Replay execution entry stages for selective pipeline re-execution."""

    RETRY_INGEST = "RETRY_INGEST"
    RETRY_NORMALIZE = "RETRY_NORMALIZE"
    RETRY_STITCH = "RETRY_STITCH"
    RETRY_DELIVER = "RETRY_DELIVER"


_REPLAY_STAGE_TO_PIPELINE_STAGE: dict[ReplayStage, PipelineStage] = {
    ReplayStage.RETRY_INGEST: PipelineStage.INGEST,
    ReplayStage.RETRY_NORMALIZE: PipelineStage.NORMALIZE,
    ReplayStage.RETRY_STITCH: PipelineStage.HYDRATE,
    ReplayStage.RETRY_DELIVER: PipelineStage.DELIVER,
}

_PIPELINE_STAGE_TO_REPLAY_STAGE: dict[PipelineStage, ReplayStage] = {
    PipelineStage.INGEST: ReplayStage.RETRY_INGEST,
    PipelineStage.NORMALIZE: ReplayStage.RETRY_NORMALIZE,
    PipelineStage.HYDRATE: ReplayStage.RETRY_STITCH,
    PipelineStage.DELIVER: ReplayStage.RETRY_DELIVER,
}


def resolve_replay_stages(
    stage: PipelineStage | ReplayStage,
    trace_id: str,
) -> Result[tuple[PipelineStage, ReplayStage], ReplayStageNotAvailableError]:
    """Resolves either a PipelineStage or ReplayStage into its canonical (PipelineStage, ReplayStage) pair."""
    if isinstance(stage, ReplayStage):
        return Result.ok((_REPLAY_STAGE_TO_PIPELINE_STAGE[stage], stage))

    replay_stage = _PIPELINE_STAGE_TO_REPLAY_STAGE.get(stage)
    if replay_stage is None:
        return Result.err(
            ReplayStageNotAvailableError.for_stage(
                trace_id,
                stage.value,
                f"Pipeline stage '{stage.value}' is not an executable replay entry stage.",
            )
        )
    return Result.ok((_REPLAY_STAGE_TO_PIPELINE_STAGE[replay_stage], replay_stage))


@dataclass(frozen=True, kw_only=True)
class ReplayStageCommand:
    """Command to replay an existing Integration Platform trace from a specific pipeline stage."""

    tenant_id: str
    trace_id: str
    stage: PipelineStage | ReplayStage
    actor: str = "SYSTEM"
    modified_payload: JsonDict | None = None


@dataclass(frozen=True, kw_only=True)
class ReplayStageResultDTO:
    """Structured result of a single deterministic stage replay."""

    original_trace_id: str
    parent_trace_id: str
    new_trace_id: str
    stage: ReplayStage
    replay_count: int
    correlation_id: str | None = None


class ReplayStageUseCase:
    """Dispatches stage replay polymorphically to isolated StageReplayProcessorPort implementations."""

    def __init__(
        self,
        uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stage_processors: Mapping[PipelineStage, StageReplayProcessorPort],
    ) -> None:
        self._uow_provider = uow_provider
        self._stage_processors = stage_processors

    async def execute(self, command: ReplayStageCommand) -> Result[ReplayStageResultDTO, IpError]:
        shard_res = await self._uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            res = await self.replay_in_uow(uow, command)
            if res.is_err:
                return res
            await uow.commit()
            return res

    async def replay_in_uow(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ReplayStageCommand,
    ) -> Result[ReplayStageResultDTO, IpError]:
        stage_res = resolve_replay_stages(command.stage, command.trace_id)
        if stage_res.is_err:
            return Result.err(stage_res.unwrap_err())
        pipeline_stage, replay_stage = stage_res.unwrap()

        processor = self._stage_processors.get(pipeline_stage)
        if processor is None:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    replay_stage.value,
                    f"No stage replay processor registered for stage '{pipeline_stage.value}'.",
                )
            )

        trace = await GetIpTraceUseCase.assemble_in_uow(
            uow,
            tenant_id=command.tenant_id,
            trace_id=command.trace_id,
            hydrate_payloads=False,
        )
        if trace is None:
            return Result.err(TraceNotFoundError.for_trace(command.trace_id))

        new_trace_id = generate_id(IpIdPrefix.TRACE.value)
        next_replay_count = trace.replay_count + 1

        outcome_res = await processor.replay(
            uow,
            trace,
            StageReplayRequest(
                tenant_id=command.tenant_id,
                parent_trace_id=command.trace_id,
                original_trace_id=trace.original_trace_id,
                new_trace_id=new_trace_id,
                next_replay_count=next_replay_count,
                correlation_id=trace.correlation_id,
                stage_label=replay_stage.value,
                actor=command.actor,
                modified_payload=command.modified_payload,
            ),
        )
        if outcome_res.is_err:
            return Result.err(outcome_res.unwrap_err())

        outcome = outcome_res.unwrap()
        dto = ReplayStageResultDTO(
            original_trace_id=outcome.original_trace_id,
            parent_trace_id=outcome.parent_trace_id,
            new_trace_id=outcome.new_trace_id,
            stage=replay_stage,
            replay_count=outcome.replay_count,
            correlation_id=outcome.correlation_id,
        )

        log_event = (
            "ip_stage_modified_and_replayed"
            if command.modified_payload is not None
            else "ip_stage_replayed"
        )
        logger.info(
            log_event,
            tenant_id=command.tenant_id,
            stage=replay_stage.value,
            pipeline_stage=pipeline_stage.value,
            parent_trace_id=command.trace_id,
            original_trace_id=dto.original_trace_id,
            new_trace_id=dto.new_trace_id,
            replay_count=dto.replay_count,
            actor=command.actor,
        )
        return Result.ok(dto)


__all__ = [
    "ReplayStage",
    "ReplayStageCommand",
    "ReplayStageResultDTO",
    "ReplayStageUseCase",
    "resolve_replay_stages",
]
