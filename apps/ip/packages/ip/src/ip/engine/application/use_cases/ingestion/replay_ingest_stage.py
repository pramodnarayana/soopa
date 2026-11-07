"""Isolated stage replay processor for PipelineStage.INGEST."""

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


class IngestStageReplayProcessor(StageReplayProcessorPort):
    """Clones an InboundRecord for replay without coupling replay orchestration to ingestion aggregates."""

    stage: PipelineStage = PipelineStage.INGEST

    async def replay(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        trace: IpTraceDTO,
        request: StageReplayRequest,
    ) -> Result[StageReplayOutcome, IpError]:
        if trace.inbound_record is None:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    request.parent_trace_id,
                    request.stage_label,
                    f"Trace '{request.parent_trace_id}' has no InboundRecord to replay.",
                )
            )
        cloned_inb = trace.inbound_record.clone_for_replay(
            new_trace_id=request.new_trace_id,
            parent_trace_id=request.parent_trace_id,
            original_trace_id=request.original_trace_id,
            replay_count=request.next_replay_count,
            modified_request_body=(
                dict(request.modified_payload) if request.modified_payload is not None else None
            ),
            actor=request.actor,
        )
        await uow.inbound_records.save(cloned_inb)
        return Result.ok(
            StageReplayOutcome(
                original_trace_id=cloned_inb.original_trace_id or request.parent_trace_id,
                parent_trace_id=request.parent_trace_id,
                new_trace_id=request.new_trace_id,
                replay_count=cloned_inb.replay_count,
                correlation_id=cloned_inb.correlation_id,
            )
        )


__all__ = ["IngestStageReplayProcessor"]
