from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from edi.application.use_cases.replay.stage_replay_processor import (
    EdiStageReplayProcessorPort,
    EdiStageReplayRequest,
)
from edi.domain.exceptions import EdiError, EdiValidationError
from edi.domain.transaction.enums import ReplayCheckpoint
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ReplayStageCommand:
    tenant_id: str
    trace_id: str
    checkpoint: ReplayCheckpoint
    actor: str = "USER"


class ReplayStageUseCase:
    """
    Replays a single EDI trace from an immutable stage checkpoint via the Transactional Outbox.
    Dispatches polymorphically through injected EdiStageReplayProcessorPort strategies.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        stage_processors: Mapping[ReplayCheckpoint, EdiStageReplayProcessorPort],
    ) -> None:
        self._uow = uow
        self._stage_processors = stage_processors

    async def execute(self, command: ReplayStageCommand) -> Result[str, EdiError]:
        processor = self._stage_processors.get(command.checkpoint)
        if processor is None:
            return Result.fail(
                EdiValidationError.with_message(
                    f"Unsupported replay checkpoint '{command.checkpoint}'.",
                    details={"checkpoint": str(command.checkpoint)},
                )
            )

        result = await processor.replay(
            self._uow,
            EdiStageReplayRequest(
                tenant_id=command.tenant_id,
                trace_id=command.trace_id,
                actor=command.actor,
            ),
        )
        if result.is_err:
            return result

        new_trace_id = result.unwrap()
        await self._uow.commit()
        logger.info(
            "replay_stage.completed",
            tenant_id=command.tenant_id,
            original_trace_id=command.trace_id,
            replay_trace_id=new_trace_id,
            checkpoint=command.checkpoint.value,
        )
        return Result.ok(new_trace_id)
