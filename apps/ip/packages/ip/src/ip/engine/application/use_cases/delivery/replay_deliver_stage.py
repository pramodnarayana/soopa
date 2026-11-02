"""Isolated stage replay processor for PipelineStage.DELIVER."""

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


class DeliverStageReplayProcessor(StageReplayProcessorPort):
    """Clones the latest OutboundRecord for delivery retry without coupling replay orchestration to dispatch aggregates."""

    stage: PipelineStage = PipelineStage.DELIVER

    async def replay(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        trace: IpTraceDTO,
        request: StageReplayRequest,
    ) -> Result[StageReplayOutcome, IpError]:
        if not trace.outbound_records:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    request.parent_trace_id,
                    request.stage_label,
                    f"Trace '{request.parent_trace_id}' has no OutboundRecord to deliver.",
                )
            )
        latest_outbound = trace.outbound_records[-1]
        cloned_out = latest_outbound.clone_for_delivery_retry(
            new_trace_id=request.new_trace_id,
            parent_trace_id=request.parent_trace_id,
            original_trace_id=request.original_trace_id,
            replay_count=request.next_replay_count,
            actor=request.actor,
        )
        await uow.outbound_records.save(cloned_out)
        return Result.ok(
            StageReplayOutcome(
                original_trace_id=request.original_trace_id,
                parent_trace_id=request.parent_trace_id,
                new_trace_id=request.new_trace_id,
                replay_count=request.next_replay_count,
                correlation_id=request.correlation_id,
            )
        )


__all__ = ["DeliverStageReplayProcessor"]
