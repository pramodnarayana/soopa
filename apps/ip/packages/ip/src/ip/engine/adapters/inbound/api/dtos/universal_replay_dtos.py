"""HTTP Request and Response DTOs for Universal Multi-Stage Replay API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict


class UniversalReplayPreviewHttpRequest(BaseModel):
    """Payload to evaluate side-effects and boundaries of a proposed multi-stage replay."""

    target_id: str = Field(..., description="Batch ID, Record ID, or Stream Name to replay")
    target_stage: str = Field(
        ...,
        description="Target pipeline stage: STAGE_1_RAW_INGRESS, STAGE_2_STAGED_REPLICA, STAGE_3_CANONICAL_MODEL, STAGE_4_WIRE_EGRESS",
    )
    target_type: str = Field(
        default="BATCH",
        description="Target type: BATCH, RECORD, STREAM",
    )
    modified_payload: JsonDict | None = Field(
        default=None,
        description="Optional payload override for replay simulation",
    )


class UniversalReplayPreviewHttpResponse(BaseModel):
    """Calculated side-effects and impact summary of a proposed replay."""

    target_id: str
    target_type: str
    target_stage: str
    affected_entity_count: int
    total_record_count: int
    window_start_utc: datetime
    window_end_utc: datetime
    estimated_duration_seconds: float
    will_deliver_to_egress: bool
    requires_idempotency_key: bool


class UniversalExecuteReplayHttpRequest(BaseModel):
    """Payload to initiate a multi-stage replay execution."""

    target_id: str = Field(..., description="Batch ID, Record ID, or Stream Name to replay")
    target_stage: str = Field(
        ...,
        description="Target pipeline stage: STAGE_1_RAW_INGRESS, STAGE_2_STAGED_REPLICA, STAGE_3_CANONICAL_MODEL, STAGE_4_WIRE_EGRESS",
    )
    reason: str = Field(..., description="Operational justification for the replay")
    idempotency_key: str = Field(
        ..., description="Unique client idempotency key to prevent duplicate runs"
    )
    target_type: str = Field(
        default="BATCH",
        description="Target type: BATCH, RECORD, STREAM",
    )
    payload_override: JsonDict | None = Field(
        default=None,
        description="Optional payload override for corrected replay",
    )
    original_trace_id: str | None = Field(
        default=None,
        description="Optional lineage sextet original trace ID",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Optional external correlation identifier",
    )


class UniversalReplayExecutionHttpResponse(BaseModel):
    """Immediate outcome of initiating a multi-stage replay."""

    replay_id: str
    target_id: str
    target_type: str
    trace_id: str
    target_stage: str
    status: str
    initiated_at_utc: datetime
