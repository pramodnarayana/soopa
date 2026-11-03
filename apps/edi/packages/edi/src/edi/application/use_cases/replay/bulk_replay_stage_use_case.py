from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from edi.application.use_cases.replay.stage_replay_processor import (
    EdiBulkStageReplayRequest,
    EdiStageReplayProcessorPort,
)
from edi.domain.exceptions import EdiError, EdiValidationError
from edi.domain.transaction.enums import ReplayCheckpoint
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class BulkReplayStageCommand:
    tenant_id: str
    trace_ids: tuple[str, ...]
    checkpoint: ReplayCheckpoint
    actor: str = "USER"
    command_key: str | None = None


class BulkReplayStageUseCase:
    """
    Bulk-replays EDI traces from a stage checkpoint via the Transactional Outbox.
    Dispatches polymorphically through injected EdiStageReplayProcessorPort strategies.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        stage_processors: Mapping[ReplayCheckpoint, EdiStageReplayProcessorPort],
    ) -> None:
        self._uow = uow
        self._stage_processors = stage_processors

    async def execute(self, command: BulkReplayStageCommand) -> Result[int, EdiError]:
        processor = self._stage_processors.get(command.checkpoint)
        if processor is None:
            return Result.fail(
                EdiValidationError.with_message(
                    f"Unsupported replay checkpoint '{command.checkpoint}'.",
                    details={"checkpoint": str(command.checkpoint)},
                )
            )

        result = await processor.bulk_replay(
            self._uow,
            EdiBulkStageReplayRequest(
                tenant_id=command.tenant_id,
                trace_ids=command.trace_ids,
                actor=command.actor,
                command_key=command.command_key,
            ),
        )
        if result.is_err:
            return result

        processed_count = result.unwrap()
        await self._uow.commit()
        logger.info(
            "bulk_replay_stage.completed",
            tenant_id=command.tenant_id,
            checkpoint=command.checkpoint.value,
            processed_count=processed_count,
        )
        return Result.ok(processed_count)
