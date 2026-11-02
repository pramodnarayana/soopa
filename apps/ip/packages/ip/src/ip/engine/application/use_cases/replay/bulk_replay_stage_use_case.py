"""Use case for bulk-replaying multiple Integration Platform stage traces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import structlog

from ip.engine.application.use_cases.replay.replay_stage_use_case import (
    ReplayStage,
    ReplayStageCommand,
    ReplayStageUseCase,
    resolve_replay_stages,
)
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class BulkReplayFailureItemDTO:
    """Details of a single trace that could not be replayed during a bulk replay operation."""

    trace_id: str
    error_code: IpErrorCode
    message: str


@dataclass(frozen=True, kw_only=True)
class BulkReplayStageResultDTO:
    """Structured result of a bulk stage replay operation."""

    stage: ReplayStage
    replayed_count: int
    succeeded_trace_ids: tuple[str, ...]
    new_trace_ids: tuple[str, ...]
    failed_items: tuple[BulkReplayFailureItemDTO, ...] = ()


@dataclass(frozen=True, kw_only=True)
class BulkReplayStageCommand:
    """Command to replay a deduplicated batch of stage trace IDs."""

    tenant_id: str
    trace_ids: tuple[str, ...]
    stage: PipelineStage | ReplayStage
    actor: str = "SYSTEM"


class BulkReplayStageUseCase:
    """Replays a batch of unique traces from a specific stage and reports per-trace outcomes."""

    def __init__(
        self,
        uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stage_processors: Mapping[PipelineStage, StageReplayProcessorPort],
    ) -> None:
        self._uow_provider = uow_provider
        self._single_replay = ReplayStageUseCase(
            uow_provider=uow_provider,
            stage_processors=stage_processors,
        )

    async def execute(
        self, command: BulkReplayStageCommand
    ) -> Result[BulkReplayStageResultDTO, IpError]:
        stage_res = resolve_replay_stages(
            command.stage,
            command.trace_ids[0] if command.trace_ids else "bulk",
        )
        if stage_res.is_err:
            return Result.err(stage_res.unwrap_err())
        _, replay_stage = stage_res.unwrap()

        shard_res = await self._uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        unique_trace_ids = list(dict.fromkeys(t for t in command.trace_ids if t))
        if not unique_trace_ids:
            return Result.ok(
                BulkReplayStageResultDTO(
                    stage=replay_stage,
                    replayed_count=0,
                    succeeded_trace_ids=(),
                    new_trace_ids=(),
                    failed_items=(),
                )
            )

        shard_id, shard_dsn = shard_res.unwrap()
        succeeded: list[str] = []
        new_traces: list[str] = []
        failures: list[BulkReplayFailureItemDTO] = []

        async with self._uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            for trace_id in unique_trace_ids:
                res = await self._single_replay.replay_in_uow(
                    uow,
                    ReplayStageCommand(
                        tenant_id=command.tenant_id,
                        trace_id=trace_id,
                        stage=replay_stage,
                        actor=command.actor,
                    ),
                )
                if res.is_ok:
                    dto = res.unwrap()
                    succeeded.append(trace_id)
                    new_traces.append(dto.new_trace_id)
                else:
                    err = res.unwrap_err()
                    failures.append(
                        BulkReplayFailureItemDTO(
                            trace_id=trace_id,
                            error_code=err.code,
                            message=err.message,
                        )
                    )

            if succeeded:
                await uow.commit()

        logger.info(
            "ip_bulk_stages_replayed",
            tenant_id=command.tenant_id,
            stage=replay_stage.value,
            replayed_count=len(succeeded),
            failed_count=len(failures),
            actor=command.actor,
        )
        return Result.ok(
            BulkReplayStageResultDTO(
                stage=replay_stage,
                replayed_count=len(succeeded),
                succeeded_trace_ids=tuple(succeeded),
                new_trace_ids=tuple(new_traces),
                failed_items=tuple(failures),
            )
        )


__all__ = [
    "BulkReplayFailureItemDTO",
    "BulkReplayStageCommand",
    "BulkReplayStageResultDTO",
    "BulkReplayStageUseCase",
]
