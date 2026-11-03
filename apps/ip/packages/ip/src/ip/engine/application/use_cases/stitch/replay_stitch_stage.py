"""Isolated stage replay processor for PipelineStage.HYDRATE (Stitch)."""

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


class StitchStageReplayProcessor(StageReplayProcessorPort):
    """Clones NormalizedRecords for stitch replay without coupling replay orchestration to normalization aggregates."""

    stage: PipelineStage = PipelineStage.HYDRATE

    async def replay(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        trace: IpTraceDTO,
        request: StageReplayRequest,
    ) -> Result[StageReplayOutcome, IpError]:
        if not trace.normalized_records:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    request.parent_trace_id,
                    request.stage_label,
                    f"Trace '{request.parent_trace_id}' has no NormalizedRecord to stitch.",
                )
            )
        target_records = (
            (trace.normalized_records[-1],)
            if request.modified_payload is not None
            else trace.normalized_records
        )
        for idx, norm in enumerate(target_records):
            cloned_norm = norm.clone_for_replay(
                new_trace_id=request.new_trace_id,
                parent_trace_id=request.parent_trace_id,
                original_trace_id=request.original_trace_id,
                replay_count=request.next_replay_count,
                modified_canonical_data=(
                    dict(request.modified_payload) if request.modified_payload is not None else None
                ),
                actor=request.actor,
            )
            if idx > 0:
                cloned_norm.clear_trace_events()
            await uow.normalized_records.save(cloned_norm)

        return Result.ok(
            StageReplayOutcome(
                original_trace_id=request.original_trace_id,
                parent_trace_id=request.parent_trace_id,
                new_trace_id=request.new_trace_id,
                replay_count=request.next_replay_count,
                correlation_id=request.correlation_id,
            )
        )


__all__ = ["StitchStageReplayProcessor"]
