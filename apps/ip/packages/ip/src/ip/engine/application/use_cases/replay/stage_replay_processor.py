"""Polymorphic per-stage replay processor protocol and DTOs for Integration Platform replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.application.responses import IpTraceDTO
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class StageReplayRequest:
    """Immutable execution context passed to an isolated stage replay processor."""

    tenant_id: str
    parent_trace_id: str
    original_trace_id: str
    new_trace_id: str
    next_replay_count: int
    correlation_id: str | None
    stage_label: str
    actor: str = "SYSTEM"
    modified_payload: JsonDict | None = None


@dataclass(frozen=True, kw_only=True)
class StageReplayOutcome:
    """Immutable outcome produced by a stage replay processor."""

    original_trace_id: str
    parent_trace_id: str
    new_trace_id: str
    replay_count: int
    correlation_id: str | None = None


class StageReplayProcessorPort(Protocol):
    """Polymorphic processor contract responsible for replaying a single pipeline stage."""

    stage: PipelineStage

    async def replay(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        trace: IpTraceDTO,
        request: StageReplayRequest,
    ) -> Result[StageReplayOutcome, IpError]: ...


__all__ = [
    "StageReplayOutcome",
    "StageReplayProcessorPort",
    "StageReplayRequest",
]
