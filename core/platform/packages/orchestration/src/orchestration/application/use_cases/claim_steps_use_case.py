"""Use case for fair multi-tenant dequeue, token-bucket rate limit enforcement, and step claiming."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
    QueueItemKind,
    RunStatus,
    TimerEventPrefix,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.matching import MatchEvent
from orchestration.domain.run import StepRun, WorkflowRun
from orchestration.domain.scheduling import QueueItem
from orchestration.ports.inbound.step_handler_port import (
    StepContext,
    WorkflowDefinitionRegistryPort,
)
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ClaimStepsCommand:
    """Command for a worker to claim up to `free_slots` ready steps fairly across tenants."""

    worker_id: str
    queue_name: str = "default"
    free_slots: int = 10
    lease_ttl: timedelta = timedelta(seconds=30)
    per_tenant_cap: int = 10
    max_active_tenants: int = 50
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class ClaimedStepDTO:
    """Claimed step descriptor with resolved input payload and StepContext for execution."""

    context: StepContext
    workflow_id: str
    workflow_version: int
    step_type: str
    input_payload: JsonDict
    attempt_id: str


@dataclass(frozen=True, kw_only=True)
class ClaimStepsResultDTO:
    """Summary of claimed steps, parked rate-limited items, and woken timers."""

    claimed_steps: tuple[ClaimedStepDTO, ...]
    parked_step_ids: tuple[str, ...]
    woken_timer_step_ids: tuple[str, ...]


class ClaimStepsUseCase:
    """Unpauses ready rate-limited items, dequeues a fair multi-tenant batch, enforces token-bucket
    rate limits (parking and releasing concurrency slots if rate-limited), and claims active leases.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        step_scheduler: WorkflowStepSchedulerService,
        match_resolver: ResolveMatchConditionsUseCase,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._step_scheduler = step_scheduler
        self._match_resolver = match_resolver

    async def execute(
        self, command: ClaimStepsCommand
    ) -> Result[ClaimStepsResultDTO, WorkflowError]:
        claimed_steps: list[ClaimedStepDTO] = []
        parked_step_ids: list[str] = []
        woken_timer_step_ids: list[str] = []

        async with self._uow_factory() as uow:
            await self._unpause_ready_rate_limited_items(
                uow=uow,
                limit=command.free_slots * 2,
                now=command.now,
            )

            dequeue_res = await uow.queue.dequeue_fair_batch(
                queue_name=command.queue_name,
                free_slots=command.free_slots,
                now=command.now,
                per_tenant_cap=command.per_tenant_cap,
                max_active_tenants=command.max_active_tenants,
            )

            for item in dequeue_res.selected_items:
                await self._process_dequeued_item(
                    uow=uow,
                    item=item,
                    command=command,
                    claimed_steps=claimed_steps,
                    parked_step_ids=parked_step_ids,
                    woken_timer_step_ids=woken_timer_step_ids,
                )

            await uow.commit()

        if claimed_steps or parked_step_ids or woken_timer_step_ids:
            logger.info(
                "orchestration_steps_claimed_batch",
                worker_id=command.worker_id,
                queue_name=command.queue_name,
                claimed_count=len(claimed_steps),
                parked_count=len(parked_step_ids),
                woken_timers_count=len(woken_timer_step_ids),
            )

        return Result.ok(
            ClaimStepsResultDTO(
                claimed_steps=tuple(claimed_steps),
                parked_step_ids=tuple(parked_step_ids),
                woken_timer_step_ids=tuple(woken_timer_step_ids),
            )
        )

    async def _unpause_ready_rate_limited_items(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        limit: int,
        now: datetime,
    ) -> None:
        unpaused_items = await uow.queue.unpause_ready_items(now=now, limit=limit)
        for paused in unpaused_items:
            run_res = await uow.runs.get_by_id(paused.tenant_id, paused.run_id)
            if run_res.is_err:
                continue
            run = run_res.unwrap()
            defn_res = self._definition_registry.get(
                run.workflow_id, run.workflow_version
            )
            if defn_res.is_err:
                continue
            defn = defn_res.unwrap()
            target_step = self._find_step_by_id(run, paused.step_run_id)
            if target_step is None:
                continue
            node = defn.get_node(target_step.node_key)
            if node is None:
                continue
            await self._step_scheduler.schedule_ready_step(
                uow=uow,
                run=run,
                step=target_step,
                definition=defn,
                node=node,
                available_at=now,
                now=now,
            )

    async def _process_dequeued_item(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        item: QueueItem,
        command: ClaimStepsCommand,
        claimed_steps: list[ClaimedStepDTO],
        parked_step_ids: list[str],
        woken_timer_step_ids: list[str],
    ) -> None:
        run_res = await uow.runs.get_by_id(item.tenant_id, item.run_id)
        if run_res.is_err:
            return
        run = run_res.unwrap()

        if item.item_kind in (QueueItemKind.SLEEP_WAKE, QueueItemKind.WAIT_TIMEOUT):
            await self._wake_timer_item(uow=uow, item=item, now=command.now)
            woken_timer_step_ids.append(item.step_run_id)
            return

        defn_res = self._definition_registry.get(run.workflow_id, run.workflow_version)
        if defn_res.is_err:
            run.status = RunStatus.BLOCKED_VERSION_UNAVAILABLE
            await uow.runs.save(run)
            return
        definition = defn_res.unwrap()

        step = self._find_step_by_id(run, item.step_run_id)
        if step is None or step.retry_count != item.retry_count:
            return

        node = definition.get_node(step.node_key)
        if node is None:
            return

        if await self._park_if_rate_limited(
            uow=uow,
            run=run,
            step=step,
            definition=definition,
            node=node,
            item=item,
            now=command.now,
        ):
            parked_step_ids.append(step.id)
            return

        claimed = await self._claim_step_lease(
            uow=uow,
            run=run,
            step=step,
            node=node,
            command=command,
        )
        if claimed is not None:
            claimed_steps.append(claimed)

    async def _wake_timer_item(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        item: QueueItem,
        now: datetime,
    ) -> None:
        event_key = (
            TimerEventPrefix.SLEEP.format_key(item.step_run_id)
            if item.item_kind == QueueItemKind.SLEEP_WAKE
            else TimerEventPrefix.WAIT_TIMEOUT.format_key(item.step_run_id)
        )
        await self._match_resolver.resolve_in_uow(
            uow=uow,
            initial_event=MatchEvent(
                tenant_id=item.tenant_id,
                condition_kind=ConditionKind.SLEEP,
                event_key=event_key,
                resource_hint=item.step_run_id,
                payload={},
                occurred_at=now,
            ),
            now=now,
        )

    async def _park_if_rate_limited(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        step: StepRun,
        definition: WorkflowDefinition,
        node: NodeDefinition,
        item: QueueItem,
        now: datetime,
    ) -> bool:
        if node.rate_limit_policy is None:
            return False

        rl_policy = node.rate_limit_policy
        bucket = await uow.rate_limits.get_or_create_bucket(
            tenant_id=run.tenant_id,
            rate_limit_key=rl_policy.rate_limit_key,
            capacity=rl_policy.capacity,
            refill_per_second=rl_policy.refill_per_second,
            now=now,
        )
        updated_bucket, consumed_ok, requeue_after = bucket.try_consume(
            rl_policy.units, now
        )
        await uow.rate_limits.save_bucket(updated_bucket)
        if consumed_ok or requeue_after is None:
            return False

        await uow.queue.park_rate_limited(
            item=item,
            rate_limit_key=rl_policy.rate_limit_key,
            requeue_after=requeue_after,
            now=now,
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
                now=now,
            )
        logger.info(
            "orchestration_step_parked_rate_limited",
            tenant_id=run.tenant_id,
            run_id=run.id,
            step_run_id=step.id,
            rate_limit_key=rl_policy.rate_limit_key,
            requeue_after=requeue_after.isoformat(),
        )
        return True

    @staticmethod
    async def _claim_step_lease(
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        step: StepRun,
        node: NodeDefinition,
        command: ClaimStepsCommand,
    ) -> ClaimedStepDTO | None:
        claim_res = run.claim_step(
            node_key=step.node_key,
            worker_id=command.worker_id,
            lease_ttl=command.lease_ttl,
            step_timeout=node.step_timeout,
            now=command.now,
        )
        if claim_res.is_err:
            return None

        attempt, lease = claim_res.unwrap()
        await uow.runs.save(run)
        await uow.runs.save_attempt(attempt)
        await uow.runs.acquire_lease(lease)

        input_payload = await uow.payloads.resolve_step_input(
            tenant_id=run.tenant_id,
            step_run_id=step.id,
        )
        context = StepContext(
            tenant_id=run.tenant_id,
            run_id=run.id,
            step_run_id=step.id,
            node_key=step.node_key,
            retry_count=step.retry_count,
            app_retry_count=step.app_retry_count,
            internal_retry_count=step.internal_retry_count,
            idempotency_key=f"{run.id}:{step.node_key}:{step.app_retry_count}",
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            deadline=lease.timeout_at,
        )
        return ClaimedStepDTO(
            context=context,
            workflow_id=run.workflow_id,
            workflow_version=run.workflow_version,
            step_type=node.step_type,
            input_payload=input_payload,
            attempt_id=attempt.id,
        )

    @staticmethod
    def _find_step_by_id(run: WorkflowRun, step_run_id: str) -> StepRun | None:
        return next(
            (s for s in run.steps.values() if s.id == step_run_id),
            None,
        )


__all__ = [
    "ClaimStepsCommand",
    "ClaimStepsResultDTO",
    "ClaimStepsUseCase",
    "ClaimedStepDTO",
]
