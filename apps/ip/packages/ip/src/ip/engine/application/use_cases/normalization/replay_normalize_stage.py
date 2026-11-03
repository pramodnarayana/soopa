"""Isolated stage replay processor for PipelineStage.NORMALIZE."""

from __future__ import annotations

from ip.engine.application.responses import IpTraceDTO
from ip.engine.application.use_cases.replay.stage_replay_processor import (
    StageReplayOutcome,
    StageReplayProcessorPort,
    StageReplayRequest,
)
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import IpError, ReplayStageNotAvailableError, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort


class NormalizeStageReplayProcessor(StageReplayProcessorPort):
    """Schedules normalization replay on ReplicaRecords via aggregate behavior without external field mutation."""

    stage: PipelineStage = PipelineStage.NORMALIZE

    async def replay(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        trace: IpTraceDTO,
        request: StageReplayRequest,
    ) -> Result[StageReplayOutcome, IpError]:
        if not trace.replica_records:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    request.parent_trace_id,
                    request.stage_label,
                    f"Trace '{request.parent_trace_id}' has no ReplicaRecord to normalize.",
                )
            )
        for idx, replica in enumerate(trace.replica_records):
            replica.schedule_normalization_replay(
                new_trace_id=request.new_trace_id,
                parent_trace_id=request.parent_trace_id,
                original_trace_id=request.original_trace_id,
                replay_count=request.next_replay_count,
                actor=request.actor,
            )
            if idx > 0:
                replica.clear_trace_events()
            await uow.replica_records.save(replica)

        return Result.ok(
            StageReplayOutcome(
                original_trace_id=request.original_trace_id,
                parent_trace_id=request.parent_trace_id,
                new_trace_id=request.new_trace_id,
                replay_count=request.next_replay_count,
                correlation_id=request.correlation_id,
            )
        )


__all__ = ["NormalizeStageReplayProcessor"]
