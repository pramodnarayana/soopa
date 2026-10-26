"""Use case for completing a workflow step, releasing leases/concurrency slots, and advancing CNF matches."""

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
    AttemptStatus,
    ConditionKind,
    InternalStepEventKey,
    NodeKind,
    PayloadType,
    RunStatus,
    StepFailureCode,
    StepStatus,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.matching import MatchEvent, MatchPredicateEvaluatorPort
from orchestration.domain.run import PayloadRecord, StepAttempt, StepRun, WorkflowRun
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class CompleteStepCommand:
    """Command to record successful step completion with fencing retry_count verification."""

    tenant_id: str
    run_id: str
    node_key: str
    fencing_retry_count: int
    worker_id: str
    attempt_id: str
    output_payload: JsonDict = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class CompleteStepResultDTO:
    """Result of completing a step and propagating downstream DAG transitions."""

    run_id: str
    step_run_id: str
    step_status: StepStatus
    run_status: RunStatus
    queued_child_step_ids: tuple[str, ...]


class CompleteStepUseCase:
    """Verifies fencing token, stores STEP_OUTPUT payload, releases active lease and concurrency slot,
    and propagates `step.completed` through the Hatchet CNF match engine.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        step_scheduler: WorkflowStepSchedulerService,
        match_resolver: ResolveMatchConditionsUseCase,
        predicate_evaluator: MatchPredicateEvaluatorPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._step_scheduler = step_scheduler
        self._match_resolver = match_resolver
        self._predicate_evaluator = predicate_evaluator

    async def execute(
        self, command: CompleteStepCommand
    ) -> Result[CompleteStepResultDTO, WorkflowError]:
        async with self._uow_factory() as uow:
            run_res = await uow.runs.get_by_id(command.tenant_id, command.run_id)
            if run_res.is_err:
                return Result.err(run_res.unwrap_err())
            run = run_res.unwrap()

            defn_res = self._definition_registry.get(run.workflow_id, run.workflow_version)
            if defn_res.is_err:
                return Result.err(defn_res.unwrap_err())
            definition = defn_res.unwrap()

            step_res = run.get_step(command.node_key)
            if step_res.is_err:
                return Result.err(step_res.unwrap_err())
            step = step_res.unwrap()
            node = definition.get_node(command.node_key)

            repeat_outcome = await self._evaluate_repeat_until_if_needed(
                uow=uow,
                run=run,
                step=step,
                definition=definition,
                node=node,
                command=command,
            )
            if repeat_outcome is not None:
                return repeat_outcome

            comp_res = run.complete_step(
                node_key=command.node_key,
                fencing_retry_count=command.fencing_retry_count,
                now=command.now,
            )
            if comp_res.is_err:
                return Result.err(comp_res.unwrap_err())
            completed_step = comp_res.unwrap()

            await self._record_step_completion(
                uow=uow,
                run=run,
                completed_step=completed_step,
                definition=definition,
                command=command,
            )

            match_res = await self._match_resolver.resolve_in_uow(
                uow=uow,
                initial_event=MatchEvent(
                    tenant_id=run.tenant_id,
                    condition_kind=ConditionKind.PARENT_OVERRIDE,
                    event_key=InternalStepEventKey.COMPLETED.value,
                    resource_hint=completed_step.id,
                    payload=command.output_payload,
                    occurred_at=command.now,
                ),
                now=command.now,
            )
            if match_res.is_err:
                return Result.err(match_res.unwrap_err())
            match_dto = match_res.unwrap()

            final_run = await self._finalize_run_resources(
                uow=uow,
                run=run,
                definition=definition,
                now=command.now,
            )
            await uow.commit()

        logger.info(
            "workflow_step_completed",
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            node_key=command.node_key,
            step_run_id=completed_step.id,
            run_status=final_run.status.value,
        )

        return Result.ok(
            CompleteStepResultDTO(
                run_id=final_run.id,
                step_run_id=completed_step.id,
                step_status=completed_step.status,
                run_status=final_run.status,
                queued_child_step_ids=match_dto.queued_step_ids,
            )
        )

    async def _evaluate_repeat_until_if_needed(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        step: StepRun,
        definition: WorkflowDefinition,
        node: NodeDefinition | None,
        command: CompleteStepCommand,
    ) -> Result[CompleteStepResultDTO, WorkflowError] | None:
        if node is None or node.kind != NodeKind.REPEAT_UNTIL or node.repeat_until is None:
            return None

        condition_met = (
            self._predicate_evaluator.evaluate(
                node.repeat_until.predicate_id, command.output_payload
            )
            if self._predicate_evaluator is not None
            else False
        )
        if condition_met:
            return None

        if step.iteration_count + 1 < node.repeat_until.max_iterations:
            return await self._reschedule_repeat_until_iteration(
                uow=uow,
                run=run,
                definition=definition,
                node=node,
                command=command,
            )

        return await self._fail_exhausted_repeat_until(
            uow=uow,
            run=run,
            definition=definition,
            node=node,
            command=command,
        )

    async def _reschedule_repeat_until_iteration(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        command: CompleteStepCommand,
    ) -> Result[CompleteStepResultDTO, WorkflowError]:
        assert node.repeat_until is not None
        retry_res = run.reschedule_step_repeat_until(
            node_key=command.node_key,
            fencing_retry_count=command.fencing_retry_count,
            delay=node.repeat_until.interval,
        )
        if retry_res.is_err:
            return Result.err(retry_res.unwrap_err())
        retried_step = retry_res.unwrap()
        await uow.runs.release_lease(retried_step.id)
        await self._release_and_advance_step_concurrency(
            uow=uow,
            tenant_id=run.tenant_id,
            step_run_id=retried_step.id,
            definition=definition,
            now=command.now,
        )
        await self._step_scheduler.schedule_ready_step(
            uow=uow,
            run=run,
            step=retried_step,
            definition=definition,
            node=node,
            available_at=command.now + node.repeat_until.interval,
            now=command.now,
        )
        await uow.runs.save(run)
        await uow.commit()
        return Result.ok(
            CompleteStepResultDTO(
                run_id=run.id,
                step_run_id=retried_step.id,
                step_status=retried_step.status,
                run_status=run.status,
                queued_child_step_ids=(),
            )
        )

    async def _fail_exhausted_repeat_until(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        command: CompleteStepCommand,
    ) -> Result[CompleteStepResultDTO, WorkflowError]:
        assert node.repeat_until is not None
        fail_res = run.fail_step_terminally(
            node_key=command.node_key,
            fencing_retry_count=command.fencing_retry_count,
            failure_code=StepFailureCode.TIMEOUT,
            failure_detail=(
                f"REPEAT_UNTIL exhausted max_iterations ({node.repeat_until.max_iterations})."
            ),
            now=command.now,
        )
        if fail_res.is_err:
            return Result.err(fail_res.unwrap_err())
        failed_step = fail_res.unwrap()
        await uow.runs.release_lease(failed_step.id)
        await self._release_and_advance_step_concurrency(
            uow=uow,
            tenant_id=run.tenant_id,
            step_run_id=failed_step.id,
            definition=definition,
            now=command.now,
        )
        await uow.runs.save(run)
        await self._match_resolver.resolve_in_uow(
            uow=uow,
            initial_event=MatchEvent(
                tenant_id=run.tenant_id,
                condition_kind=ConditionKind.PARENT_OVERRIDE,
                event_key=InternalStepEventKey.FAILED.value,
                resource_hint=failed_step.id,
                payload={},
                occurred_at=command.now,
            ),
            now=command.now,
        )
        refreshed_res = await uow.runs.get_by_id(run.tenant_id, run.id)
        final_run = refreshed_res.unwrap() if refreshed_res.is_ok else run
        final_run.finalize_after_match_propagation(now=command.now)
        await uow.runs.save(final_run)

        final_run = await self._finalize_run_resources(
            uow=uow,
            run=final_run,
            definition=definition,
            now=command.now,
        )
        await uow.commit()
        return Result.ok(
            CompleteStepResultDTO(
                run_id=final_run.id,
                step_run_id=failed_step.id,
                step_status=failed_step.status,
                run_status=final_run.status,
                queued_child_step_ids=(),
            )
        )

    async def _record_step_completion(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        completed_step: StepRun,
        definition: WorkflowDefinition,
        command: CompleteStepCommand,
    ) -> None:
        await uow.runs.release_lease(completed_step.id)
        await uow.runs.save_attempt(
            StepAttempt(
                id=command.attempt_id,
                step_run_id=completed_step.id,
                tenant_id=run.tenant_id,
                retry_count=completed_step.retry_count,
                app_retry_count=completed_step.app_retry_count,
                internal_retry_count=completed_step.internal_retry_count,
                worker_id=command.worker_id,
                status=AttemptStatus.SUCCEEDED,
                is_app_error=False,
                outcome_code="OK",
                started_at=command.now,
                finished_at=command.now,
            )
        )
        await uow.payloads.save_payload(
            PayloadRecord.create_inline(
                tenant_id=run.tenant_id,
                owner_id=completed_step.id,
                owner_created_at=completed_step.created_at,
                payload_type=PayloadType.STEP_OUTPUT,
                content=command.output_payload,
            )
        )
        await uow.runs.save(run)
        await self._release_and_advance_step_concurrency(
            uow=uow,
            tenant_id=run.tenant_id,
            step_run_id=completed_step.id,
            definition=definition,
            now=command.now,
        )

    async def _release_and_advance_step_concurrency(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        tenant_id: str,
        step_run_id: str,
        definition: WorkflowDefinition,
        now: datetime,
    ) -> None:
        released_keys = await uow.concurrency.release_slot_for_step(
            tenant_id=tenant_id,
            step_run_id=step_run_id,
        )
        for strat_id, conc_key in released_keys:
            await self._step_scheduler.evaluate_and_advance_concurrency_key(
                uow=uow,
                tenant_id=tenant_id,
                definition=definition,
                strategy_id=strat_id,
                concurrency_key=conc_key,
                now=now,
            )

    async def _finalize_run_resources(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        now: datetime,
    ) -> WorkflowRun:
        refreshed_res = await uow.runs.get_by_id(run.tenant_id, run.id)
        final_run = refreshed_res.unwrap() if refreshed_res.is_ok else run
        if final_run.status in (
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        ):
            released_run_keys = await uow.concurrency.release_slots_for_run(
                tenant_id=final_run.tenant_id,
                run_id=final_run.id,
            )
            for strat_id, conc_key in released_run_keys:
                await self._step_scheduler.evaluate_and_advance_concurrency_key(
                    uow=uow,
                    tenant_id=final_run.tenant_id,
                    definition=definition,
                    strategy_id=strat_id,
                    concurrency_key=conc_key,
                    now=now,
                )
            await uow.idempotency.release_on_terminal_status(
                tenant_id=final_run.tenant_id,
                workflow_id=final_run.workflow_id,
                run_id=final_run.id,
            )
        return final_run


__all__ = [
    "CompleteStepCommand",
    "CompleteStepResultDTO",
    "CompleteStepUseCase",
]
