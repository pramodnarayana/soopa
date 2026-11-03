"""HTTP Request and Response DTOs for the Integration Platform Stage Replay API."""

from __future__ import annotations

from ip.engine.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageResultDTO,
)
from ip.engine.application.use_cases.replay.replay_stage_use_case import (
    ReplayStage,
    ReplayStageResultDTO,
)
from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict


class ReplayStageHttpRequest(BaseModel):
    """Payload to replay an Integration Platform trace from a specific stage."""

    stage: ReplayStage = Field(
        ...,
        description="Target pipeline stage to replay from (RETRY_INGEST, RETRY_NORMALIZE, RETRY_STITCH, RETRY_DELIVER)",
    )


class ModifyAndReplayHttpRequest(BaseModel):
    """Payload to override an Ingest or Stitch payload and trigger a new replay trace."""

    stage: ReplayStage = Field(
        ...,
        description="Target stage for payload modification (RETRY_INGEST or RETRY_STITCH)",
    )
    modified_payload: JsonDict = Field(
        ...,
        description="Replacement JSON object for the Ingest request body or Stitch canonical data",
    )


class ReplayStageHttpResponse(BaseModel):
    """Response returned when a single stage replay or modify-and-replay is accepted."""

    status: str = "ACCEPTED"
    original_trace_id: str
    parent_trace_id: str
    new_trace_id: str
    stage: str
    replay_count: int
    correlation_id: str | None = None


class BulkReplayHttpRequest(BaseModel):
    """Payload to bulk-replay up to 100 traces from a target stage."""

    trace_ids: list[str] = Field(..., min_length=1, max_length=100)
    stage: ReplayStage


class BulkReplayFailureItemHttpResponse(BaseModel):
    """Per-trace error item for a trace that could not be replayed during a bulk replay."""

    trace_id: str
    error_code: str
    message: str


class BulkReplayHttpResponse(BaseModel):
    """Response returned when a bulk stage replay operation completes."""

    status: str = "ACCEPTED"
    stage: str
    replayed_count: int
    succeeded_trace_ids: list[str] = Field(default_factory=list)
    new_trace_ids: list[str] = Field(default_factory=list)
    failed_items: list[BulkReplayFailureItemHttpResponse] = Field(default_factory=list)


def map_replay_result_to_http(dto: ReplayStageResultDTO) -> ReplayStageHttpResponse:
    return ReplayStageHttpResponse(
        status="ACCEPTED",
        original_trace_id=dto.original_trace_id,
        parent_trace_id=dto.parent_trace_id,
        new_trace_id=dto.new_trace_id,
        stage=dto.stage.value,
        replay_count=dto.replay_count,
        correlation_id=dto.correlation_id,
    )


def map_bulk_replay_result_to_http(dto: BulkReplayStageResultDTO) -> BulkReplayHttpResponse:
    return BulkReplayHttpResponse(
        status="ACCEPTED",
        stage=dto.stage.value,
        replayed_count=dto.replayed_count,
        succeeded_trace_ids=list(dto.succeeded_trace_ids),
        new_trace_ids=list(dto.new_trace_ids),
        failed_items=[
            BulkReplayFailureItemHttpResponse(
                trace_id=item.trace_id,
                error_code=item.error_code.value,
                message=item.message,
            )
            for item in dto.failed_items
        ],
    )


__all__ = [
    "BulkReplayFailureItemHttpResponse",
    "BulkReplayHttpRequest",
    "BulkReplayHttpResponse",
    "ModifyAndReplayHttpRequest",
    "ReplayStageHttpRequest",
    "ReplayStageHttpResponse",
    "map_bulk_replay_result_to_http",
    "map_replay_result_to_http",
]
