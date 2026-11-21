"""Universal platform replay DTOs (core/platform/packages/replay)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from replay.domain.enums import ReplayStage, ReplayStatus, ReplayTargetType
from seedwork.domain.types import JsonDict


@dataclass(frozen=True, slots=True)
class ReplayPreviewRequestDTO:
    """Request to compute the side-effects and boundaries of a proposed replay."""

    target_id: str
    tenant_id: str
    target_stage: ReplayStage
    target_type: ReplayTargetType = ReplayTargetType.BATCH
    modified_payload: JsonDict | None = None


@dataclass(frozen=True, slots=True)
class ReplayPreviewResponseDTO:
    """Calculated side-effects and impact summary of a proposed replay."""

    target_id: str
    target_type: ReplayTargetType
    target_stage: ReplayStage
    affected_entity_count: int
    total_record_count: int
    window_start_utc: datetime
    window_end_utc: datetime
    estimated_duration_seconds: float
    will_deliver_to_egress: bool
    requires_idempotency_key: bool


@dataclass(frozen=True, slots=True)
class ExecuteReplayCommandDTO:
    """Command to execute a multi-stage replay across any domain."""

    target_id: str
    tenant_id: str
    target_stage: ReplayStage
    actor: str
    reason: str
    idempotency_key: str
    target_type: ReplayTargetType = ReplayTargetType.BATCH
    payload_override: JsonDict | None = None
    original_trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayExecutionResultDTO:
    """Immediate outcome of initiating a multi-stage replay."""

    replay_id: str
    target_id: str
    target_type: ReplayTargetType
    trace_id: str
    target_stage: ReplayStage
    status: ReplayStatus
    initiated_at_utc: datetime
