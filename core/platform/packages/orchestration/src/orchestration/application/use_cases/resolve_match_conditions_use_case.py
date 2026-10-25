"""Use case and in-transaction service for resolving Hatchet v1 CNF WorkflowMatch conditions."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from observability import ObservabilityProvider
from seedwork.domain.types import JsonDict

from orchestration.application.services.step_scheduler_service import (
    WorkflowStepSchedulerService,
)
from orchestration.domain.constants import (
    ConditionKind,
    InternalStepEventKey,
    MatchAction,
    MatchKind,
    NodeKind,
    PayloadType,
    QueueItemKind,
    RunStatus,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.matching import (
    DagMatchCompiler,
    MatchEvent,
    MatchPredicateEvaluatorPort,
    WorkflowMatch,
)
from orchestration.domain.run import PayloadRecord, StepRun, WorkflowRun
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ResolveMatchConditionsCommand:
    """Command to evaluate an incoming event or timer expiration against active CNF WorkflowMatches."""

    tenant_id: str
    condition_kind: ConditionKind
    event_key: str
    resource_hint: str | None = None
    payload: JsonDict = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class ResolveMatchConditionsResultDTO:
    """Summary of CNF matches satisfied and steps advanced by an event."""

    satisfied_match_ids: tuple[str, ...]
    queued_step_ids: tuple[str, ...]
    skipped_step_ids: tuple[str, ...]
    cancelled_step_ids: tuple[str, ...]
    waiting_step_ids: tuple[str, ...]


@dataclass
class _ResolutionAccumulator:
    """Internal mutable accumulator for a single BFS match resolution pass."""

    event_queue: deque[MatchEvent]
    satisfied_match_ids: list[str] = field(default_factory=list)
    queued_step_ids: list[str] = field(default_factory=list)
    skipped_step_ids: list[str] = field(default_factory=list)
    cancelled_step_ids: list[str] = field(default_factory=list)
    waiting_step_ids: list[str] = field(default_factory=list)
    affected_runs: dict[tuple[str, str], WorkflowRun] = field(default_factory=dict)


class ResolveMatchConditionsUseCase:
    """Evaluates incoming `MatchEvent` signals against CNF `WorkflowMatch` records and advances DAG execution."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        step_scheduler: WorkflowStepSchedulerService,
        predicate_evaluator: MatchPredicateEvaluatorPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._step_scheduler = step_scheduler
        self._predicate_evaluator = predicate_evaluator

    async def execute(
        self, command: ResolveMatchConditionsCommand
    ) -> Result[ResolveMatchConditionsResultDTO, WorkflowError]:
        event = MatchEvent(
            tenant_id=command.tenant_id,
            condition_kind=command.condition_kind,
            event_key=command.event_key,
            resource_hint=command.resource_hint,
            payload=command.payload,
            occurred_at=command.now,
        )
        async with self._uow_factory() as uow:
            res = await self.resolve_in_uow(
                uow=uow,
                initial_event=event,
                now=command.now,
            )
            if res.is_err:
                return res
            await uow.commit()
            return res

    async def resolve_in_uow(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        initial_event: MatchEvent,
        now: datetime,
    ) -> Result[ResolveMatchConditionsResultDTO, WorkflowError]:
        """Propagate an initial MatchEvent and any cascading internal step events within an active UoW."""
        acc = _ResolutionAccumulator(event_queue=deque([initial_event]))

        while acc.event_queue:
            current_event = acc.event_queue.popleft()
            candidates = await uow.matches.find_unsatisfied_for_event(
                tenant_id=current_event.tenant_id,
                condition_kind=current_event.condition_kind,
                event_key=current_event.event_key,
                resource_hint=current_event.resource_hint,
            )
            for match in candidates:
                step_err = await self._evaluate_candidate_match(
                    uow=uow,
                    match=match,
                    event=current_event,
                    acc=acc,
                    now=now,
                )
                if step_err is not None:
                    return Result.err(step_err)

        await self._finalize_affected_runs(
            uow=uow,
            affected_runs=acc.affected_runs,
            now=now,
        )

        logger.info(
            "workflow_matches_resolved",
            tenant_id=initial_event.tenant_id,
            event_key=initial_event.event_key,
            satisfied_count=len(acc.satisfied_match_ids),
            queued_count=len(acc.queued_step_ids),
            skipped_count=len(acc.skipped_step_ids),
            cancelled_count=len(acc.cancelled_step_ids),
        )

        return Result.ok(
            ResolveMatchConditionsResultDTO(
                satisfied_match_ids=tuple(acc.satisfied_match_ids),
                queued_step_ids=tuple(acc.queued_step_ids),
                skipped_step_ids=tuple(acc.skipped_step_ids),
                cancelled_step_ids=tuple(acc.cancelled_step_ids),
                waiting_step_ids=tuple(acc.waiting_step_ids),
            )
        )

    async def _evaluate_candidate_match(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        match: WorkflowMatch,
        event: MatchEvent,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> WorkflowError | None:
        updated_match = match.apply_event(event, self._predicate_evaluator)
        if updated_match == match:
            return None

        await uow.matches.save_match(updated_match)
        if not updated_match.is_satisfied or updated_match.resolved_action is None:
            return None

        acc.satisfied_match_ids.append(updated_match.id)
        run_res = await self._get_or_load_run(
            uow=uow,
            tenant_id=updated_match.tenant_id,
            run_id=updated_match.run_id,
            affected_runs=acc.affected_runs,
        )
        if run_res.is_err:
            return run_res.unwrap_err()
        run = run_res.unwrap()

        defn_res = self._definition_registry.get(
            run.workflow_id, run.workflow_version
        )
        if defn_res.is_err:
            run.status = RunStatus.BLOCKED_VERSION_UNAVAILABLE
            await uow.runs.save(run)
            return defn_res.unwrap_err()
        definition = defn_res.unwrap()
        node = definition.get_node(updated_match.node_key)
        if node is None:
            return None

        return await self._dispatch_resolved_action(
            uow=uow,
            run=run,
            definition=definition,
            node=node,
            updated_match=updated_match,
            acc=acc,
            now=now,
        )

    @staticmethod
    async def _get_or_load_run(
        *,
        uow: WorkflowUnitOfWorkPort,
        tenant_id: str,
        run_id: str,
        affected_runs: dict[tuple[str, str], WorkflowRun],
    ) -> Result[WorkflowRun, WorkflowError]:
        run_key = (tenant_id, run_id)
        existing = affected_runs.get(run_key)
        if existing is not None:
            return Result.ok(existing)
        run_res = await uow.runs.get_by_id(tenant_id, run_id)
        if run_res.is_err:
            return Result.err(run_res.unwrap_err())
        loaded = run_res.unwrap()
        affected_runs[run_key] = loaded
        return Result.ok(loaded)

    async def _dispatch_resolved_action(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        updated_match: WorkflowMatch,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> WorkflowError | None:
        action = updated_match.resolved_action
        aggregated_input = updated_match.aggregated_payload()

        if action == MatchAction.SKIP:
            self._apply_skip_action(run=run, node=node, acc=acc, now=now)
            return None

        if action == MatchAction.CANCEL:
            self._apply_cancel_or_timeout_action(
                run=run,
                node=node,
                updated_match=updated_match,
                acc=acc,
                now=now,
            )
            return None

        if action == MatchAction.CREATE_MATCH:
            return await self._apply_create_signal_match_action(
                uow=uow,
                run=run,
                node=node,
                aggregated_input=aggregated_input,
                acc=acc,
                now=now,
            )

        return await self._apply_queue_action(
            uow=uow,
            run=run,
            definition=definition,
            node=node,
            aggregated_input=aggregated_input,
            acc=acc,
            now=now,
        )

    @staticmethod
    def _apply_skip_action(
        *,
        run: WorkflowRun,
        node: NodeDefinition,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> None:
        skip_res = run.skip_step(node_key=node.node_key, now=now)
        if skip_res.is_ok:
            skipped_step = skip_res.unwrap()
            acc.skipped_step_ids.append(skipped_step.id)
            acc.event_queue.append(
                MatchEvent(
                    tenant_id=run.tenant_id,
                    condition_kind=ConditionKind.PARENT_OVERRIDE,
                    event_key=InternalStepEventKey.SKIPPED.value,
                    resource_hint=skipped_step.id,
                    payload={},
                    occurred_at=now,
                )
            )

    @staticmethod
    def _apply_cancel_or_timeout_action(
        *,
        run: WorkflowRun,
        node: NodeDefinition,
        updated_match: WorkflowMatch,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> None:
        if (
            updated_match.kind == MatchKind.SIGNAL_WAIT
            and node.kind == NodeKind.WAIT_FOR_EVENT
        ):
            to_res = run.timeout_step(node_key=node.node_key, now=now)
            if to_res.is_ok:
                timed_out_step = to_res.unwrap()
                acc.cancelled_step_ids.append(timed_out_step.id)
                acc.event_queue.append(
                    MatchEvent(
                        tenant_id=run.tenant_id,
                        condition_kind=ConditionKind.PARENT_OVERRIDE,
                        event_key=InternalStepEventKey.TIMED_OUT.value,
                        resource_hint=timed_out_step.id,
                        payload={},
                        occurred_at=now,
                    )
                )
            return

        cancel_res = run.cancel_step(
            node_key=node.node_key,
            reason="Cancelled by upstream CNF condition.",
            now=now,
        )
        if cancel_res.is_ok:
            cancelled_step = cancel_res.unwrap()
            acc.cancelled_step_ids.append(cancelled_step.id)
            acc.event_queue.append(
                MatchEvent(
                    tenant_id=run.tenant_id,
                    condition_kind=ConditionKind.PARENT_OVERRIDE,
                    event_key=InternalStepEventKey.CANCELLED.value,
                    resource_hint=cancelled_step.id,
                    payload={},
                    occurred_at=now,
                )
            )

    async def _apply_create_signal_match_action(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        node: NodeDefinition,
        aggregated_input: JsonDict,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> WorkflowError | None:
        wait_res = run.mark_step_waiting(node.node_key)
        if wait_res.is_err:
            return wait_res.unwrap_err()
        waiting_step = wait_res.unwrap()
        acc.waiting_step_ids.append(waiting_step.id)

        signal_match = DagMatchCompiler.build_signal_wait_match(
            tenant_id=run.tenant_id,
            run_id=run.id,
            step_run_id=waiting_step.id,
            step_created_at=waiting_step.created_at,
            node=node,
            existing_data=aggregated_input,
            now=now,
        )
        await uow.matches.save_match(signal_match)
        await self._enqueue_signal_timer_if_needed(
            uow=uow,
            run=run,
            signal_match=signal_match,
            node_queue_name=node.queue_name,
        )
        return None

    async def _apply_queue_action(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        aggregated_input: JsonDict,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> WorkflowError | None:
        step_res = run.get_step(node.node_key)
        if step_res.is_err:
            return step_res.unwrap_err()
        target_step = step_res.unwrap()

        await uow.payloads.save_payload(
            PayloadRecord.create_inline(
                tenant_id=run.tenant_id,
                owner_id=target_step.id,
                owner_created_at=target_step.created_at,
                payload_type=PayloadType.STEP_INPUT,
                content=aggregated_input,
            )
        )

        if node.kind == NodeKind.SLEEP or (
            node.kind == NodeKind.WAIT_FOR_EVENT and not node.step_type
        ):
            return await self._complete_control_node_inline(
                uow=uow,
                run=run,
                node=node,
                target_step=target_step,
                aggregated_input=aggregated_input,
                acc=acc,
                now=now,
            )

        if (
            node.kind == NodeKind.BRANCH
            and not node.step_type
            and node.branch_predicate_id is not None
        ):
            return await self._evaluate_branch_node_inline(
                uow=uow,
                run=run,
                node=node,
                target_step=target_step,
                aggregated_input=aggregated_input,
                acc=acc,
                now=now,
            )

        ready_res = run.mark_step_ready(node.node_key)
        if ready_res.is_err:
            return ready_res.unwrap_err()
        ready_step = ready_res.unwrap()
        acc.queued_step_ids.append(ready_step.id)
        await self._step_scheduler.schedule_ready_step(
            uow=uow,
            run=run,
            step=ready_step,
            definition=definition,
            node=node,
            available_at=now,
            now=now,
        )
        return None

    @staticmethod
    async def _complete_control_node_inline(
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        node: NodeDefinition,
        target_step: StepRun,
        aggregated_input: JsonDict,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> WorkflowError | None:
        comp_res = run.complete_step(
            node_key=node.node_key,
            fencing_retry_count=target_step.retry_count,
            now=now,
        )
        if comp_res.is_err:
            return comp_res.unwrap_err()
        await uow.payloads.save_payload(
            PayloadRecord.create_inline(
                tenant_id=run.tenant_id,
                owner_id=target_step.id,
                owner_created_at=target_step.created_at,
                payload_type=PayloadType.STEP_OUTPUT,
                content=aggregated_input,
            )
        )
        acc.event_queue.append(
            MatchEvent(
                tenant_id=run.tenant_id,
                condition_kind=ConditionKind.PARENT_OVERRIDE,
                event_key=InternalStepEventKey.COMPLETED.value,
                resource_hint=target_step.id,
                payload=aggregated_input,
                occurred_at=now,
            )
        )
        return None

    async def _evaluate_branch_node_inline(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        node: NodeDefinition,
        target_step: StepRun,
        aggregated_input: JsonDict,
        acc: _ResolutionAccumulator,
        now: datetime,
    ) -> WorkflowError | None:
        assert node.branch_predicate_id is not None
        branch_passed = (
            self._predicate_evaluator.evaluate(
                node.branch_predicate_id, aggregated_input
            )
            if self._predicate_evaluator is not None
            else False
        )
        if not branch_passed:
            self._apply_skip_action(run=run, node=node, acc=acc, now=now)
            return None

        ready_res = run.mark_step_ready(node.node_key)
        if ready_res.is_err:
            return ready_res.unwrap_err()
        return await self._complete_control_node_inline(
            uow=uow,
            run=run,
            node=node,
            target_step=target_step,
            aggregated_input=aggregated_input,
            acc=acc,
            now=now,
        )

    @staticmethod
    async def _finalize_affected_runs(
        *,
        uow: WorkflowUnitOfWorkPort,
        affected_runs: dict[tuple[str, str], WorkflowRun],
        now: datetime,
    ) -> None:
        for run in affected_runs.values():
            run.finalize_after_match_propagation(now=now)
            await uow.runs.save(run)
            if run.status in (
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            ):
                await uow.idempotency.release_on_terminal_status(
                    tenant_id=run.tenant_id,
                    workflow_id=run.workflow_id,
                    run_id=run.id,
                )

    @staticmethod
    async def _enqueue_signal_timer_if_needed(
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        signal_match: WorkflowMatch,
        node_queue_name: str,
    ) -> None:
        for cond in signal_match.conditions:
            if (
                cond.condition_kind == ConditionKind.SLEEP
                and cond.timeout_at is not None
            ):
                item_kind = (
                    QueueItemKind.SLEEP_WAKE
                    if cond.action == MatchAction.QUEUE
                    else QueueItemKind.WAIT_TIMEOUT
                )
                await uow.queue.enqueue(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    step_run_id=signal_match.step_run_id,
                    step_created_at=signal_match.step_created_at,
                    retry_count=0,
                    item_kind=item_kind,
                    queue_name=node_queue_name,
                    priority=run.priority,
                    available_at=cond.timeout_at,
                    concurrency_key=run.concurrency_key,
                )


__all__ = [
    "ResolveMatchConditionsCommand",
    "ResolveMatchConditionsResultDTO",
    "ResolveMatchConditionsUseCase",
]
