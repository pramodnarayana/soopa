"""Use case for modifying an L1 or L3 payload and replaying the transaction with full lineage."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict

from ip.engine.application.dtos.trace import ReplayTransactionResultDTO
from ip.engine.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionCommand,
    ReplayTransactionUseCase,
)
from ip.engine.domain.enums import ReplayStage
from ip.engine.domain.exceptions import (
    InvalidReplayPayloadError,
    IpError,
    ReplayStageNotAvailableError,
    Result,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort


@dataclass(frozen=True, kw_only=True)
class ModifyAndReplayCommand:
    """Command to override a record's payload at L1 or L3 and trigger a new replay trace."""

    tenant_id: str
    trace_id: str
    stage: ReplayStage
    modified_payload: JsonDict
    actor: str = "SYSTEM"


class ModifyAndReplayTransactionUseCase:
    """Validates payload override constraints and delegates replay execution to ReplayTransactionUseCase."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._replay_use_case = ReplayTransactionUseCase(uow_provider=uow_provider)

    async def execute(
        self, command: ModifyAndReplayCommand
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        if not command.modified_payload:
            return Result.err(
                InvalidReplayPayloadError.for_trace(
                    command.trace_id,
                    "Modified replay payload must be a non-empty JSON object.",
                )
            )

        if command.stage not in (ReplayStage.RETRY_INGEST, ReplayStage.RETRY_STITCH):
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    command.stage.value,
                    f"Modify-and-replay is supported only for RETRY_INGEST and RETRY_STITCH (got '{command.stage.value}').",
                )
            )

        return await self._replay_use_case.execute(
            ReplayTransactionCommand(
                tenant_id=command.tenant_id,
                trace_id=command.trace_id,
                stage=command.stage,
                actor=command.actor,
                modified_payload=command.modified_payload,
            )
        )


__all__ = ["ModifyAndReplayCommand", "ModifyAndReplayTransactionUseCase"]
