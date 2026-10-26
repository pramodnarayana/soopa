"""Use case executing a single durable Stitch worker tick across claimed workflow steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from observability import ObservabilityProvider
from orchestration.application.use_cases import (
    ClaimedStepDTO,
    ClaimStepsCommand,
    ClaimStepsUseCase,
    CompleteStepCommand,
    CompleteStepUseCase,
    FailStepCommand,
    FailStepUseCase,
)
from orchestration.domain.constants import StepFailureCode
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.failures import TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepHandlerRegistryPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ExecuteStitchWorkerTickCommand:
    """Command to claim and execute up to `free_slots` ready Stitch workflow steps."""

    worker_id: str
    queue_name: str = "default"
    free_slots: int = 10
    lease_ttl: timedelta = timedelta(seconds=30)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class StitchWorkerTickResultDTO:
    """Summary of steps completed, failed/retried, parked for rate limits, and woken timers."""

    completed_step_ids: tuple[str, ...]
    failed_or_retried_step_ids: tuple[str, ...]
    parked_step_ids: tuple[str, ...]
    woken_timer_step_ids: tuple[str, ...]


class ExecuteStitchWorkerTickUseCase:
    """Claims a fair multi-tenant batch of ready steps, invokes their registered `StepHandlerPort`,
    and commits outcomes via `CompleteStepUseCase` or `FailStepUseCase`.
    """

    def __init__(
        self,
        *,
        claim_steps_use_case: ClaimStepsUseCase,
        complete_step_use_case: CompleteStepUseCase,
        fail_step_use_case: FailStepUseCase,
        handler_registry: StepHandlerRegistryPort,
    ) -> None:
        self._claim_steps = claim_steps_use_case
        self._complete_step = complete_step_use_case
        self._fail_step = fail_step_use_case
        self._handler_registry = handler_registry

    async def execute(
        self, command: ExecuteStitchWorkerTickCommand
    ) -> Result[StitchWorkerTickResultDTO, WorkflowError]:
        claim_res = await self._claim_steps.execute(
            ClaimStepsCommand(
                worker_id=command.worker_id,
                queue_name=command.queue_name,
                free_slots=command.free_slots,
                lease_ttl=command.lease_ttl,
                now=command.now,
            )
        )
        if claim_res.is_err:
            return Result.err(claim_res.unwrap_err())
        claim_dto = claim_res.unwrap()

        completed_ids: list[str] = []
        failed_ids: list[str] = []

        for claimed in claim_dto.claimed_steps:
            succeeded = await self._execute_single_claimed_step(
                claimed=claimed,
                worker_id=command.worker_id,
                now=command.now,
            )
            if succeeded:
                completed_ids.append(claimed.context.step_run_id)
            else:
                failed_ids.append(claimed.context.step_run_id)

        return Result.ok(
            StitchWorkerTickResultDTO(
                completed_step_ids=tuple(completed_ids),
                failed_or_retried_step_ids=tuple(failed_ids),
                parked_step_ids=claim_dto.parked_step_ids,
                woken_timer_step_ids=claim_dto.woken_timer_step_ids,
            )
        )

    async def _execute_single_claimed_step(
        self,
        *,
        claimed: ClaimedStepDTO,
        worker_id: str,
        now: datetime,
    ) -> bool:
        handler_res = self._handler_registry.get(claimed.step_type)
        if handler_res.is_err:
            await self._fail_step.execute(
                FailStepCommand(
                    tenant_id=claimed.context.tenant_id,
                    run_id=claimed.context.run_id,
                    node_key=claimed.context.node_key,
                    fencing_retry_count=claimed.context.retry_count,
                    worker_id=worker_id,
                    attempt_id=claimed.attempt_id,
                    failure=TerminalFailure(
                        code=StepFailureCode.VALIDATION_REJECTED,
                        detail=handler_res.unwrap_err().message,
                    ),
                    now=now,
                )
            )
            return False

        handler = handler_res.unwrap()
        exec_res = await handler.execute(claimed.context, claimed.input_payload)
        if exec_res.is_ok:
            await self._complete_step.execute(
                CompleteStepCommand(
                    tenant_id=claimed.context.tenant_id,
                    run_id=claimed.context.run_id,
                    node_key=claimed.context.node_key,
                    fencing_retry_count=claimed.context.retry_count,
                    worker_id=worker_id,
                    attempt_id=claimed.attempt_id,
                    output_payload=exec_res.unwrap(),
                    now=now,
                )
            )
            return True

        await self._fail_step.execute(
            FailStepCommand(
                tenant_id=claimed.context.tenant_id,
                run_id=claimed.context.run_id,
                node_key=claimed.context.node_key,
                fencing_retry_count=claimed.context.retry_count,
                worker_id=worker_id,
                attempt_id=claimed.attempt_id,
                failure=exec_res.unwrap_err(),
                now=now,
            )
        )
        return False


__all__ = [
    "ExecuteStitchWorkerTickCommand",
    "ExecuteStitchWorkerTickUseCase",
    "StitchWorkerTickResultDTO",
]
