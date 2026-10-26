"""Use case for handling step failures via StepErrorPolicyPort, Hatchet 3-counter retries, and 429 rate-limit parking."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from observability import ObservabilityProvider

from orchestration.application.services.step_scheduler_service import (
    WorkflowStepSchedulerService,
)
from orchestration.application.use_cases.resolve_match_conditions_use_case import (
    ResolveMatchConditionsUseCase,
)
from orchestration.domain.constants import (
    AttemptStatus,
    ConditionKind,
    ErrorDecisionKind,
    InternalStepEventKey,
    QueueItemKind,
    RunStatus,
    StepStatus,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.exceptions import (
    FencingTokenMismatchError,
    InvalidTransitionError,
    Result,
    WorkflowError,
)
from orchestration.domain.failures import ErrorPolicyDecision, RetryableFailure, StepFailure
from orchestration.domain.matching import MatchEvent
from orchestration.domain.run import StepAttempt, StepRun, WorkflowRun
from orchestration.domain.scheduling import QueueItem
from orchestration.ports.inbound.step_handler_port import (
    StepErrorPolicyPort,
    WorkflowDefinitionRegistryPort,
)
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class FailStepCommand:
    """Command to record a step failure and execute the StepErrorPolicyPort decision."""

    tenant_id: str
    run_id: str
    node_key: str
    fencing_retry_count: int
    worker_id: str
    attempt_id: str
    failure: StepFailure
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class FailStepResultDTO:
    """Result of processing a step failure."""

    run_id: str
    step_run_id: str
    decision: ErrorDecisionKind
    step_status: StepStatus
    run_status: RunStatus
    retry_count: int
    app_retry_count: int
    internal_retry_count: int


class FailStepUseCase:
    """Evaluates StepErrorPolicyPort and executes:
    - PARK_FOR_RATE_LIMIT: pauses RateLimitBucket (`GREATEST`), parks item, releases concurrency slot, preserves `app_retry_count`.
    - RETRY: increments `retry_count` + (`app_retry_count` or `internal_retry_count`), re-enqueues after backoff.
    - FAIL_TERMINAL / FAIL_AMBIGUOUS_OPERATOR_GATE: marks step FAILED and propagates `step.failed` via CNF matches.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        error_policy: StepErrorPolicyPort,
        step_scheduler: WorkflowStepSchedulerService,
        match_resolver: ResolveMatchConditionsUseCase,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._error_policy = error_policy
        self._step_scheduler = step_scheduler
        self._match_resolver = match_resolver

    async def execute(self, command: FailStepCommand) -> Result[FailStepResultDTO, WorkflowError]:
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

            if step.retry_count != command.fencing_retry_count:
                return Result.err(
                    FencingTokenMismatchError.for_step(
                        step_run_id=step.id,
                        expected_retry_count=step.retry_count,
                        actual_retry_count=command.fencing_retry_count,
                    )
                )

            if step.status != StepStatus.RUNNING:
                return Result.err(
                    InvalidTransitionError.for_entity(
                        entity_type="StepRun",
                        entity_id=step.id,
                        current_status=step.status.value,
                        attempted_action="fail_step",
                    )
                )

            node = definition.get_node(command.node_key)
            if node is None:
                return Result.err(run.get_step("__missing__").unwrap_err())

            decision = self._error_policy.decide(
                failure=command.failure,
                step_run=step,
                node_definition=node,
            )
            is_app_error = (
                command.failure.is_app_error
                if isinstance(command.failure, RetryableFailure)
                else True
            )

            await self._record_failed_attempt_and_release_slot(
                uow=uow,
                run=run,
                step=step,
                definition=definition,
                decision=decision,
                is_app_error=is_app_error,
                command=command,
            )

            if decision.kind == ErrorDecisionKind.PARK_FOR_RATE_LIMIT:
                return await self._handle_rate_limit_park(
                    uow=uow,
                    run=run,
                    node=node,
                    decision=decision,
                    command=command,
                )

            if decision.kind == ErrorDecisionKind.RETRY:
                return await self._handle_retry(
                    uow=uow,
                    run=run,
                    definition=definition,
                    node=node,
                    decision=decision,
                    is_app_error=is_app_error,
                    command=command,
                )

            return await self._handle_terminal_failure(
                uow=uow,
                run=run,
                definition=definition,
                decision=decision,
                command=command,
            )

    async def _record_failed_attempt_and_release_slot(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        step: StepRun,
        definition: WorkflowDefinition,
        decision: ErrorPolicyDecision,
        is_app_error: bool,
        command: FailStepCommand,
    ) -> None:
        await uow.runs.release_lease(step.id)
        await uow.runs.save_attempt(
            StepAttempt(
                id=command.attempt_id,
                step_run_id=step.id,
                tenant_id=run.tenant_id,
                retry_count=step.retry_count,
                app_retry_count=step.app_retry_count,
                internal_retry_count=step.internal_retry_count,
                worker_id=command.worker_id,
                status=AttemptStatus.FAILED,
                is_app_error=is_app_error,
                outcome_code=decision.failure_code.value,
                outcome_detail=decision.failure_detail,
                started_at=command.now,
                finished_at=command.now,
            )
        )
        released_keys = await uow.concurrency.release_slot_for_step(
            tenant_id=run.tenant_id,
            step_run_id=step.id,
        )
        for strat_id, conc_key in released_keys:
            await self._step_scheduler.evaluate_and_advance_concurrency_key(
                uow=uow,
                tenant_id=run.tenant_id,
                definition=definition,
                strategy_id=strat_id,
                concurrency_key=conc_key,
                now=command.now,
            )

    @staticmethod
    async def _handle_rate_limit_park(
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        node: NodeDefinition,
        decision: ErrorPolicyDecision,
        command: FailStepCommand,
    ) -> Result[FailStepResultDTO, WorkflowError]:
        rl_key = (
            node.rate_limit_policy.rate_limit_key
            if node.rate_limit_policy is not None
            else f"{run.workflow_id}:{node.node_key}"
        )
        capacity = node.rate_limit_policy.capacity if node.rate_limit_policy is not None else 60
        refill_rate = (
            node.rate_limit_policy.refill_per_second if node.rate_limit_policy is not None else 1.0
        )
        bucket = await uow.rate_limits.get_or_create_bucket(
            tenant_id=run.tenant_id,
            rate_limit_key=rl_key,
            capacity=capacity,
            refill_per_second=refill_rate,
            now=command.now,
        )
        paused_bucket = bucket.apply_upstream_pause(decision.delay, command.now)
        await uow.rate_limits.save_bucket(paused_bucket)

        park_res = run.schedule_step_retry(
            node_key=command.node_key,
            fencing_retry_count=command.fencing_retry_count,
            failure_code=decision.failure_code,
            failure_detail=decision.failure_detail,
            delay=decision.delay,
            is_app_error=False,
            is_rate_limit_park=True,
        )
        if park_res.is_err:
            return Result.err(park_res.unwrap_err())
        parked_step = park_res.unwrap()
        parked_step.status = StepStatus.READY
        await uow.runs.save(run)

        requeue_after = paused_bucket.paused_until or (command.now + decision.delay)
        synthetic_item = QueueItem(
            id=0,
            tenant_id=run.tenant_id,
            run_id=run.id,
            step_run_id=parked_step.id,
            step_created_at=parked_step.created_at,
            retry_count=parked_step.retry_count,
            item_kind=QueueItemKind.EXECUTE,
            queue_name=node.queue_name,
            priority=run.priority,
            available_at=requeue_after,
            enqueued_at=command.now,
            concurrency_key=run.concurrency_key,
            rate_limit_key=rl_key,
            rate_limit_units=(
                node.rate_limit_policy.units if node.rate_limit_policy is not None else 1
            ),
        )
        await uow.queue.park_rate_limited(
            item=synthetic_item,
            rate_limit_key=rl_key,
            requeue_after=requeue_after,
            now=command.now,
        )
        await uow.commit()
        return Result.ok(
            FailStepResultDTO(
                run_id=run.id,
                step_run_id=parked_step.id,
                decision=decision.kind,
                step_status=parked_step.status,
                run_status=run.status,
                retry_count=parked_step.retry_count,
                app_retry_count=parked_step.app_retry_count,
                internal_retry_count=parked_step.internal_retry_count,
            )
        )

    async def _handle_retry(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        decision: ErrorPolicyDecision,
        is_app_error: bool,
        command: FailStepCommand,
    ) -> Result[FailStepResultDTO, WorkflowError]:
        retry_res = run.schedule_step_retry(
            node_key=command.node_key,
            fencing_retry_count=command.fencing_retry_count,
            failure_code=decision.failure_code,
            failure_detail=decision.failure_detail,
            delay=decision.delay,
            is_app_error=is_app_error,
            is_rate_limit_park=False,
        )
        if retry_res.is_err:
            return Result.err(retry_res.unwrap_err())
        retried_step = retry_res.unwrap()
        retried_step.status = StepStatus.READY
        await uow.runs.save(run)

        await self._step_scheduler.schedule_ready_step(
            uow=uow,
            run=run,
            step=retried_step,
            definition=definition,
            node=node,
            available_at=command.now + decision.delay,
            now=command.now,
        )
        await uow.commit()
        return Result.ok(
            FailStepResultDTO(
                run_id=run.id,
                step_run_id=retried_step.id,
                decision=decision.kind,
                step_status=retried_step.status,
                run_status=run.status,
                retry_count=retried_step.retry_count,
                app_retry_count=retried_step.app_retry_count,
                internal_retry_count=retried_step.internal_retry_count,
            )
        )

    async def _handle_terminal_failure(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        decision: ErrorPolicyDecision,
        command: FailStepCommand,
    ) -> Result[FailStepResultDTO, WorkflowError]:
        term_res = run.fail_step_terminally(
            node_key=command.node_key,
            fencing_retry_count=command.fencing_retry_count,
            failure_code=decision.failure_code,
            failure_detail=decision.failure_detail,
            now=command.now,
        )
        if term_res.is_err:
            return Result.err(term_res.unwrap_err())
        failed_step = term_res.unwrap()
        await uow.runs.save(run)

        match_res = await self._match_resolver.resolve_in_uow(
            uow=uow,
            initial_event=MatchEvent(
                tenant_id=run.tenant_id,
                condition_kind=ConditionKind.PARENT_OVERRIDE,
                event_key=InternalStepEventKey.FAILED.value,
                resource_hint=failed_step.id,
                payload={
                    "failure_code": decision.failure_code.value,
                    "failure_detail": decision.failure_detail,
                },
                occurred_at=command.now,
            ),
            now=command.now,
        )
        if match_res.is_err:
            return Result.err(match_res.unwrap_err())

        refreshed_res = await uow.runs.get_by_id(run.tenant_id, run.id)
        final_run = refreshed_res.unwrap() if refreshed_res.is_ok else run
        final_run.finalize_after_match_propagation(now=command.now)
        await uow.runs.save(final_run)

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
                    now=command.now,
                )
            await uow.idempotency.release_on_terminal_status(
                tenant_id=final_run.tenant_id,
                workflow_id=final_run.workflow_id,
                run_id=final_run.id,
            )

        await uow.commit()

        logger.error(
            "workflow_step_failed_terminally",
            tenant_id=command.tenant_id,
            run_id=command.run_id,
            node_key=command.node_key,
            step_run_id=failed_step.id,
            failure_code=decision.failure_code.value,
            run_status=final_run.status.value,
        )

        return Result.ok(
            FailStepResultDTO(
                run_id=final_run.id,
                step_run_id=failed_step.id,
                decision=decision.kind,
                step_status=failed_step.status,
                run_status=final_run.status,
                retry_count=failed_step.retry_count,
                app_retry_count=failed_step.app_retry_count,
                internal_retry_count=failed_step.internal_retry_count,
            )
        )


__all__ = ["FailStepCommand", "FailStepResultDTO", "FailStepUseCase"]
