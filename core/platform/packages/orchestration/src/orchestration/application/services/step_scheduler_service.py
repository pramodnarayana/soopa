"""Shared step scheduling and Hatchet window-function concurrency orchestration service."""

from __future__ import annotations

from datetime import datetime

from orchestration.domain.constants import NodeKind, QueueItemKind
from orchestration.domain.definition import (
    ConcurrencyPolicy,
    NodeDefinition,
    WorkflowDefinition,
)
from orchestration.domain.run import StepRun, WorkflowRun
from orchestration.domain.scheduling import ConcurrencySlot, ConcurrencyWindowEvaluator
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort


class WorkflowStepSchedulerService:
    """Coordinates Hatchet v1 concurrency slot evaluation, multi-strategy chaining, and queue insertion."""

    async def schedule_ready_step(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        step: StepRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        available_at: datetime,
        now: datetime,
    ) -> None:
        """Enqueue a READY step, evaluating workflow-level and step-level concurrency strategies if configured."""
        policies = self._collect_policies(definition, node)
        rate_limit_key = (
            node.rate_limit_policy.rate_limit_key if node.rate_limit_policy is not None else None
        )
        rate_limit_units = node.rate_limit_policy.units if node.rate_limit_policy is not None else 1
        item_kind = self._resolve_queue_item_kind(node.kind)
        concurrency_key = (
            run.concurrency_key or policies[0].key_template if policies else run.concurrency_key
        )

        if not policies:
            await uow.queue.enqueue(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_run_id=step.id,
                step_created_at=step.created_at,
                retry_count=step.retry_count,
                item_kind=item_kind,
                queue_name=node.queue_name,
                priority=run.priority,
                available_at=available_at,
                concurrency_key=concurrency_key,
                rate_limit_key=rate_limit_key,
                rate_limit_units=rate_limit_units,
            )
            return

        first_policy = policies[0]
        next_strategy_ids = tuple(p.strategy_id for p in policies[1:])
        resolved_key = run.concurrency_key or first_policy.key_template

        await uow.concurrency.insert_slot(
            tenant_id=run.tenant_id,
            strategy_id=first_policy.strategy_id,
            concurrency_key=resolved_key,
            run_id=run.id,
            step_run_id=step.id,
            step_created_at=step.created_at,
            retry_count=step.retry_count,
            priority=run.priority,
            next_strategy_ids=next_strategy_ids,
            queue_name=node.queue_name,
            rate_limit_key=rate_limit_key,
            rate_limit_units=rate_limit_units,
            now=now,
        )
        await self.evaluate_and_advance_concurrency_key(
            uow=uow,
            tenant_id=run.tenant_id,
            definition=definition,
            strategy_id=first_policy.strategy_id,
            concurrency_key=resolved_key,
            available_at=available_at,
            now=now,
            current_run=run,
        )

    async def evaluate_and_advance_concurrency_key(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        tenant_id: str,
        definition: WorkflowDefinition,
        strategy_id: str,
        concurrency_key: str,
        available_at: datetime | None = None,
        now: datetime,
        current_run: WorkflowRun | None = None,
    ) -> None:
        """Run Hatchet's window-function concurrency evaluator for `(tenant_id, strategy_id, concurrency_key)`,
        promoting multi-strategy slots, enqueueing winning slots, and cancelling evicted slots/runs.
        """
        policy = self._find_policy_by_id(definition, strategy_id)
        if policy is None:
            return

        slots = await uow.concurrency.list_slots_for_key(
            tenant_id=tenant_id,
            strategy_id=strategy_id,
            concurrency_key=concurrency_key,
        )
        if not slots:
            return

        eval_result = ConcurrencyWindowEvaluator.evaluate_key_group(
            strategy=policy.strategy,
            max_runs=policy.max_runs,
            slots=slots,
            now=now,
        )
        await uow.concurrency.apply_evaluation_result(
            tenant_id=tenant_id,
            strategy_id=strategy_id,
            concurrency_key=concurrency_key,
            result=eval_result,
        )

        # Promote multi-strategy chained slots into their next strategy
        for promoted in eval_result.promoted_to_next_strategy:
            await uow.concurrency.insert_slot(
                tenant_id=promoted.tenant_id,
                strategy_id=promoted.strategy_id,
                concurrency_key=promoted.concurrency_key,
                run_id=promoted.run_id,
                step_run_id=promoted.step_run_id,
                step_created_at=promoted.step_created_at,
                retry_count=promoted.retry_count,
                priority=promoted.priority,
                next_strategy_ids=promoted.next_strategy_ids,
                queue_name=promoted.queue_name,
                rate_limit_key=promoted.rate_limit_key,
                rate_limit_units=promoted.rate_limit_units,
                now=now,
            )
            await self.evaluate_and_advance_concurrency_key(
                uow=uow,
                tenant_id=promoted.tenant_id,
                definition=definition,
                strategy_id=promoted.strategy_id,
                concurrency_key=promoted.concurrency_key,
                available_at=available_at,
                now=now,
                current_run=current_run,
            )

        # Enqueue slots that have satisfied all concurrency strategies
        effective_available_at = available_at or now
        for ready_slot in eval_result.ready_to_enqueue:
            await uow.queue.enqueue(
                tenant_id=ready_slot.tenant_id,
                run_id=ready_slot.run_id,
                step_run_id=ready_slot.step_run_id,
                step_created_at=ready_slot.step_created_at,
                retry_count=ready_slot.retry_count,
                item_kind=QueueItemKind.EXECUTE,
                queue_name=ready_slot.queue_name,
                priority=ready_slot.priority,
                available_at=effective_available_at,
                concurrency_key=ready_slot.concurrency_key,
                rate_limit_key=ready_slot.rate_limit_key,
                rate_limit_units=ready_slot.rate_limit_units,
            )

        # Cancel runs/steps evicted by CANCEL_IN_PROGRESS, CANCEL_NEWEST, or COALESCE_LATEST
        for cancelled_slot in eval_result.cancelled_slots:
            await self._cancel_evicted_slot(
                uow=uow,
                slot=cancelled_slot,
                strategy_name=policy.strategy.value,
                now=now,
                current_run=current_run,
            )

    async def _cancel_evicted_slot(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        slot: ConcurrencySlot,
        strategy_name: str,
        now: datetime,
        current_run: WorkflowRun | None = None,
    ) -> None:
        if current_run is not None and current_run.id == slot.run_id:
            evicted_run = current_run
        else:
            run_res = await uow.runs.get_by_id(slot.tenant_id, slot.run_id)
            if run_res.is_err:
                return
            evicted_run = run_res.unwrap()

        evicted_run.cancel_run(
            reason=f"Evicted by concurrency strategy {strategy_name} on key '{slot.concurrency_key}'.",
            now=now,
        )
        await uow.runs.release_lease(slot.step_run_id)
        await uow.queue.remove_for_run(slot.tenant_id, slot.run_id)
        await uow.concurrency.release_slots_for_run(tenant_id=slot.tenant_id, run_id=slot.run_id)
        await uow.idempotency.release_on_terminal_status(
            tenant_id=slot.tenant_id,
            workflow_id=evicted_run.workflow_id,
            run_id=slot.run_id,
        )
        await uow.runs.save(evicted_run)

    @staticmethod
    def _collect_policies(
        definition: WorkflowDefinition, node: NodeDefinition
    ) -> tuple[ConcurrencyPolicy, ...]:
        policies: list[ConcurrencyPolicy] = []
        if definition.workflow_concurrency is not None:
            policies.append(definition.workflow_concurrency)
        policies.extend(node.concurrency_policies)
        return tuple(policies)

    @staticmethod
    def _find_policy_by_id(
        definition: WorkflowDefinition, strategy_id: str
    ) -> ConcurrencyPolicy | None:
        if (
            definition.workflow_concurrency is not None
            and definition.workflow_concurrency.strategy_id == strategy_id
        ):
            return definition.workflow_concurrency
        for node in definition.nodes:
            for policy in node.concurrency_policies:
                if policy.strategy_id == strategy_id:
                    return policy
        return None

    @staticmethod
    def _resolve_queue_item_kind(kind: NodeKind) -> QueueItemKind:
        if kind == NodeKind.SLEEP:
            return QueueItemKind.SLEEP_WAKE
        if kind == NodeKind.WAIT_FOR_EVENT:
            return QueueItemKind.WAIT_TIMEOUT
        return QueueItemKind.EXECUTE


__all__ = ["WorkflowStepSchedulerService"]
