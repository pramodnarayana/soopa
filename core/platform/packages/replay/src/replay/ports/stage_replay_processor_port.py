"""Polymorphic Stage Replay Processor Port implemented by domain apps."""

from __future__ import annotations

from typing import Protocol

from replay.domain.dtos import ReplayPreviewResponseDTO
from replay.domain.enums import ReplayStage
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict


class StageReplayProcessorPort(Protocol):
    """Polymorphic interface implemented by domain apps (apps/ip, apps/edi)."""

    stage: ReplayStage

    async def preview_replay(
        self,
        tenant_id: str,
        target_id: str,
        modified_payload: JsonDict | None = None,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        """Calculates side-effects and boundaries of a proposed replay for this stage."""
        ...

    async def replay_stage(
        self,
        tenant_id: str,
        target_id: str,
        new_trace_id: str,
        parent_trace_id: str,
        is_replay: bool = True,
        modified_payload: JsonDict | None = None,
    ) -> Result[bool, Exception]:
        """Re-executes the specified pipeline stage for the target batch or record."""
        ...
