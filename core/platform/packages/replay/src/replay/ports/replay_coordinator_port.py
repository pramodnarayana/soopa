"""Port for universal platform replay coordination."""

from __future__ import annotations

from typing import Protocol

from replay.domain.dtos import (
    ExecuteReplayCommandDTO,
    ReplayExecutionResultDTO,
    ReplayPreviewRequestDTO,
    ReplayPreviewResponseDTO,
)
from replay.ports.stage_replay_processor_port import StageReplayProcessorPort
from seedwork.domain.exceptions import Result


class ReplayCoordinatorPort(Protocol):
    """Abstract port for previewing and initiating multi-stage replays across any domain."""

    async def preview(
        self,
        request: ReplayPreviewRequestDTO,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        """Calculates side-effects and boundaries of a proposed replay."""
        ...

    async def execute(
        self,
        command: ExecuteReplayCommandDTO,
    ) -> Result[ReplayExecutionResultDTO, Exception]:
        """Initiates a multi-stage replay and dispatches execution to the registered processor."""
        ...

    def register_processor(self, processor: StageReplayProcessorPort) -> None:
        """Registers a stage replay processor for a specific ReplayStage."""
        ...
