"""Operator action use cases: CancelRun, ReplayFailedStep, and SkipFailedStep."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from observability import ObservabilityProvider
from seedwork.domain.types import JsonDict

from orchestration.application.services.step_scheduler_service import (
    WorkflowStepSchedulerService,
)
from orchestration.application.use_cases.resolve_match_conditions_use_case import (
    ResolveMatchConditionsUseCase,
)
from orchestration.domain.constants import (
    ConditionKind,
    InternalStepEventKey,
    PayloadType,
    RunStatus,
    StepStatus,
)
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.matching import MatchEvent
from orchestration.domain.run import PayloadRecord
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class CancelRunCommand:
    """Operator command to cancel a running, queued, or waiting WorkflowRun."""

    tenant_id: str
    run_id: str
    reason: str
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class CancelRunResultDTO:
    """Result of cancelling a WorkflowRun."""

    run_id: str
    status: RunStatus


class CancelRunUseCase:
    """Cancels all non-terminal steps on a WorkflowRun, releases leases and concurrency slots, and evicts queue items."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        step_scheduler: WorkflowStepSchedulerService,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._step_scheduler = step_scheduler

    async def execute(
        self, command: CancelRunCommand
    ) -> Result[CancelRunResultDTO, WorkflowError]:
        async with self._uow_factory() as uow:
            run_res = await uow.runs.get_by_id(command.tenant_id, command.run_id)
            if run_res.is_err:
                return Result.err(run_res.unwrap_err())
            run = run_res.unwrap()

            cancel_res = run.cancel_run(reason=command.reason, now=command.now)
            if cancel_res.is_err:
                return Result.err(cancel_res.unwrap_err())

            for step in run.steps.values():
                await uow.runs.release_lease(step.id)

            await uow.queue.remove_for_run(run.tenant_id, run.id)
            await uow.runs.save(run)

            released_keys = await uow.concurrency.release_slots_for_run(
                tenant_id=run.tenant_id,
                run_id=run.id,
            )
            defn_res = self._definition_registry.get(
                run.workflow_id, run.workflow_version
            )
            if defn_res.is_ok:
                definition = defn_res.unwrap()
                for strat_id, conc_key in released_keys:
                    await self._step_scheduler.evaluate_and_advance_concurrency_key(
                        uow=uow,
                        tenant_id=run.tenant_id,
                        definition=definition,
                        strategy_id=strat_id,
                        concurrency_key=conc_key,
                        now=command.now,
                    )

            await uow.idempotency.release_on_terminal_status(
                tenant_id=run.tenant_id,
                workflow_id=run.workflow_id,
                run_id=run.id,
            )
            await uow.commit()

        logger.info(
            "workflow_run_cancelled",
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            reason=command.reason,
        )
        return Result.ok(CancelRunResultDTO(run_id=run.id, status=run.status))


@dataclass(frozen=True, kw_only=True)
class ReplayFailedStepCommand:
    """Operator command (Hatchet ReplayTasks) to retry a failed step with reset app_retry_count=0 and incremented fencing retry_count."""

    tenant_id: str
    run_id: str
    node_key: str
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class ReplayFailedStepResultDTO:
    """Result of replaying a failed step."""

    run_id: str
    step_run_id: str
    retry_count: int
    app_retry_count: int
    step_status: StepStatus
    run_status: RunStatus


class ReplayFailedStepUseCase:
    """Re-opens a FAILED/CANCELLED run at the specified step, increments `retry_count` (fencing token),
    resets `app_retry_count = 0`, and schedules the step for execution.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        step_scheduler: WorkflowStepSchedulerService,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._step_scheduler = step_scheduler

    async def execute(
        self, command: ReplayFailedStepCommand
    ) -> Result[ReplayFailedStepResultDTO, WorkflowError]:
        async with self._uow_factory() as uow:
            run_res = await uow.runs.get_by_id(command.tenant_id, command.run_id)
            if run_res.is_err:
                return Result.err(run_res.unwrap_err())
            run = run_res.unwrap()

            defn_res = self._definition_registry.get(
                run.workflow_id, run.workflow_version
            )
            if defn_res.is_err:
                return Result.err(defn_res.unwrap_err())
            definition = defn_res.unwrap()

            replay_res = run.replay_from_failed_step(node_key=command.node_key)
            if replay_res.is_err:
                return Result.err(replay_res.unwrap_err())
            replayed_step = replay_res.unwrap()

            node = definition.get_node(command.node_key)
            if node is None:
                return Result.err(run.get_step("__missing__").unwrap_err())

            await uow.runs.save(run)
            existing_matches = await uow.matches.list_by_run(run.tenant_id, run.id)
            for match in existing_matches:
                reset_match = match.reset_for_replayed_parents({replayed_step.id})
                if reset_match != match:
                    await uow.matches.save_match(reset_match)
            await self._step_scheduler.schedule_ready_step(
                uow=uow,
                run=run,
                step=replayed_step,
                definition=definition,
                node=node,
                available_at=command.now,
                now=command.now,
            )
            await uow.commit()

        logger.info(
            "workflow_step_replayed",
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            node_key=command.node_key,
            retry_count=replayed_step.retry_count,
        )
        return Result.ok(
            ReplayFailedStepResultDTO(
                run_id=run.id,
                step_run_id=replayed_step.id,
                retry_count=replayed_step.retry_count,
                app_retry_count=replayed_step.app_retry_count,
                step_status=replayed_step.status,
                run_status=run.status,
            )
        )


@dataclass(frozen=True, kw_only=True)
class SkipFailedStepCommand:
    """Operator command to resolve an ambiguous or failed step by supplying manual output and advancing children."""

    tenant_id: str
    run_id: str
    node_key: str
    manual_output: JsonDict
    reason: str
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class SkipFailedStepResultDTO:
    """Result of operator-skipping a failed step with manual output."""

    run_id: str
    step_run_id: str
    step_status: StepStatus
    run_status: RunStatus
    queued_child_step_ids: tuple[str, ...]


class SkipFailedStepUseCase:
    """Marks a FAILED/TIMED_OUT step as SUCCEEDED with operator-supplied output and triggers downstream CNF children."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        match_resolver: ResolveMatchConditionsUseCase,
    ) -> None:
        self._uow_factory = uow_factory
        self._match_resolver = match_resolver

    async def execute(
        self, command: SkipFailedStepCommand
    ) -> Result[SkipFailedStepResultDTO, WorkflowError]:
        async with self._uow_factory() as uow:
            run_res = await uow.runs.get_by_id(command.tenant_id, command.run_id)
            if run_res.is_err:
                return Result.err(run_res.unwrap_err())
            run = run_res.unwrap()

            skip_res = run.skip_failed_step_by_operator(
                node_key=command.node_key,
                reason=command.reason,
                now=command.now,
            )
            if skip_res.is_err:
                return Result.err(skip_res.unwrap_err())
            resolved_step = skip_res.unwrap()

            await uow.payloads.save_payload(
                PayloadRecord.create_inline(
                    tenant_id=run.tenant_id,
                    owner_id=resolved_step.id,
                    owner_created_at=resolved_step.created_at,
                    payload_type=PayloadType.STEP_OUTPUT,
                    content=command.manual_output,
                )
            )
            await uow.runs.save(run)
            existing_matches = await uow.matches.list_by_run(run.tenant_id, run.id)
            for match in existing_matches:
                reset_match = match.reset_for_replayed_parents({resolved_step.id})
                if reset_match != match:
                    await uow.matches.save_match(reset_match)

            match_res = await self._match_resolver.resolve_in_uow(
                uow=uow,
                initial_event=MatchEvent(
                    tenant_id=run.tenant_id,
                    condition_kind=ConditionKind.PARENT_OVERRIDE,
                    event_key=InternalStepEventKey.COMPLETED.value,
                    resource_hint=resolved_step.id,
                    payload=command.manual_output,
                    occurred_at=command.now,
                ),
                now=command.now,
            )
            if match_res.is_err:
                return Result.err(match_res.unwrap_err())
            match_dto = match_res.unwrap()

            refreshed_res = await uow.runs.get_by_id(run.tenant_id, run.id)
            final_run = refreshed_res.unwrap() if refreshed_res.is_ok else run
            await uow.commit()

        return Result.ok(
            SkipFailedStepResultDTO(
                run_id=final_run.id,
                step_run_id=resolved_step.id,
                step_status=resolved_step.status,
                run_status=final_run.status,
                queued_child_step_ids=match_dto.queued_step_ids,
            )
        )


__all__ = [
    "CancelRunCommand",
    "CancelRunResultDTO",
    "CancelRunUseCase",
    "ReplayFailedStepCommand",
    "ReplayFailedStepResultDTO",
    "ReplayFailedStepUseCase",
    "SkipFailedStepCommand",
    "SkipFailedStepResultDTO",
    "SkipFailedStepUseCase",
]
