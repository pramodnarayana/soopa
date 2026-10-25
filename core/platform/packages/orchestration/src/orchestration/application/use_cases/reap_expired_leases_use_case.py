"""Use case for reaping expired worker leases (`is_app_error=False`) and timed-out steps (`is_app_error=True`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from observability import ObservabilityProvider
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from orchestration.application.use_cases.complete_step_use_case import (
    CompleteStepCommand,
    CompleteStepUseCase,
)
from orchestration.application.use_cases.fail_step_use_case import (
    FailStepCommand,
    FailStepUseCase,
)
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.definition import NodeDefinition
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.failures import ReconcileOutcome, RetryableFailure
from orchestration.domain.run import ActiveLease, StepRun, WorkflowRun
from orchestration.ports.inbound.step_handler_port import (
    ReconcilableStepHandlerPort,
    StepContext,
    StepHandlerRegistryPort,
    WorkflowDefinitionRegistryPort,
)
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ReapExpiredLeasesCommand:
    """Command to scan and reap expired leases and timed-out steps."""

    batch_limit: int = 100
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class ReapExpiredLeasesResultDTO:
    """Summary of reaped expired leases, reconciled steps, and timed-out steps."""

    reaped_lease_step_ids: tuple[str, ...]
    reconciled_step_ids: tuple[str, ...]
    timed_out_step_ids: tuple[str, ...]


class ReapExpiredLeasesUseCase:
    """Scans `workflow_active_leases` (`v1_task_runtime`) for:
    1. Expired worker heartbeats (`lease_expires_at <= now`):
       - If the step handler is `RECONCILABLE_EFFECT` and implements `ReconcilableStepHandlerPort`,
         calls `reconcile()` first to adopt external side effects if they already succeeded!
       - Otherwise routes to `FailStepUseCase` with `is_app_error=False` (incrementing `internal_retry_count`
         without burning `app_retry_count`, or halting on `OPERATOR_GATED_EFFECT`).
    2. Timed-out steps (`timeout_at <= now`):
       - Routes to `FailStepUseCase` with `StepFailureCode.TIMEOUT` (`is_app_error=True`).
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], WorkflowUnitOfWorkPort],
        definition_registry: WorkflowDefinitionRegistryPort,
        fail_step_use_case: FailStepUseCase,
        complete_step_use_case: CompleteStepUseCase | None = None,
        handler_registry: StepHandlerRegistryPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._definition_registry = definition_registry
        self._fail_step_use_case = fail_step_use_case
        self._complete_step_use_case = complete_step_use_case
        self._handler_registry = handler_registry

    async def execute(
        self, command: ReapExpiredLeasesCommand
    ) -> Result[ReapExpiredLeasesResultDTO, WorkflowError]:
        reaped_lease_ids: list[str] = []
        reconciled_ids: list[str] = []
        timed_out_ids: list[str] = []

        async with self._uow_factory() as uow:
            expired_leases = list(
                await uow.runs.list_expired_leases(
                    now=command.now, limit=command.batch_limit
                )
            )
            timed_out_leases = list(
                await uow.runs.list_timed_out_leases(
                    now=command.now, limit=command.batch_limit
                )
            )

        timed_out_step_set = {lease.step_run_id for lease in timed_out_leases}

        for lease in timed_out_leases:
            if await self._reap_timed_out_lease(lease=lease, now=command.now):
                timed_out_ids.append(lease.step_run_id)

        for lease in expired_leases:
            if lease.step_run_id in timed_out_step_set:
                continue
            await self._process_expired_lease(
                lease=lease,
                now=command.now,
                reconciled_ids=reconciled_ids,
                reaped_lease_ids=reaped_lease_ids,
            )

        if reaped_lease_ids or reconciled_ids or timed_out_ids:
            logger.info(
                "orchestration_leases_reaped",
                reaped_count=len(reaped_lease_ids),
                reconciled_count=len(reconciled_ids),
                timed_out_count=len(timed_out_ids),
            )

        return Result.ok(
            ReapExpiredLeasesResultDTO(
                reaped_lease_step_ids=tuple(reaped_lease_ids),
                reconciled_step_ids=tuple(reconciled_ids),
                timed_out_step_ids=tuple(timed_out_ids),
            )
        )

    async def _reap_timed_out_lease(
        self, *, lease: ActiveLease, now: datetime
    ) -> bool:
        resolved = await self._load_lease_target(lease)
        if resolved is None:
            return False
        _, step, _, _ = resolved

        res = await self._fail_step_use_case.execute(
            FailStepCommand(
                tenant_id=lease.tenant_id,
                run_id=lease.run_id,
                node_key=step.node_key,
                fencing_retry_count=lease.retry_count,
                worker_id=lease.worker_id,
                attempt_id=generate_id(SystemIdPrefix.WORKFLOW_ATTEMPT.value),
                failure=RetryableFailure(
                    code=StepFailureCode.TIMEOUT,
                    detail="Step execution exceeded timeout_at.",
                    is_app_error=True,
                ),
                now=now,
            )
        )
        return res.is_ok

    async def _process_expired_lease(
        self,
        *,
        lease: ActiveLease,
        now: datetime,
        reconciled_ids: list[str],
        reaped_lease_ids: list[str],
    ) -> None:
        resolved = await self._load_lease_target(lease)
        if resolved is None:
            return
        run, step, node, input_payload = resolved

        reconcile_outcome = await self._try_reconcile_effect(
            run=run,
            step=step,
            node=node,
            lease=lease,
            input_payload=input_payload,
        )
        if reconcile_outcome is not None and reconcile_outcome.found:
            adopted_payload = (
                dict(reconcile_outcome.adopted_output)
                if isinstance(reconcile_outcome.adopted_output, dict)
                else {}
            )
            if self._complete_step_use_case is not None:
                comp_res = await self._complete_step_use_case.execute(
                    CompleteStepCommand(
                        tenant_id=lease.tenant_id,
                        run_id=lease.run_id,
                        node_key=step.node_key,
                        fencing_retry_count=lease.retry_count,
                        worker_id=lease.worker_id,
                        attempt_id=generate_id(SystemIdPrefix.WORKFLOW_ATTEMPT.value),
                        output_payload=adopted_payload,
                        now=now,
                    )
                )
                if comp_res.is_ok:
                    reconciled_ids.append(lease.step_run_id)
                    return
            else:
                reconciled_ids.append(lease.step_run_id)
                return

        res = await self._fail_step_use_case.execute(
            FailStepCommand(
                tenant_id=lease.tenant_id,
                run_id=lease.run_id,
                node_key=step.node_key,
                fencing_retry_count=lease.retry_count,
                worker_id=lease.worker_id,
                attempt_id=generate_id(SystemIdPrefix.WORKFLOW_ATTEMPT.value),
                failure=RetryableFailure(
                    code=StepFailureCode.LEASE_EXPIRED,
                    detail="Worker heartbeat lease expired before step completion.",
                    is_app_error=False,
                ),
                now=now,
            )
        )
        if res.is_ok:
            reaped_lease_ids.append(lease.step_run_id)

    async def _load_lease_target(
        self, lease: ActiveLease
    ) -> tuple[WorkflowRun, StepRun, NodeDefinition | None, JsonDict] | None:
        async with self._uow_factory() as uow:
            run_res = await uow.runs.get_by_id(lease.tenant_id, lease.run_id)
            if run_res.is_err:
                return None
            run = run_res.unwrap()
            step = next(
                (s for s in run.steps.values() if s.id == lease.step_run_id),
                None,
            )
            if step is None:
                return None
            defn_res = self._definition_registry.get(
                run.workflow_id, run.workflow_version
            )
            node = (
                defn_res.unwrap().get_node(step.node_key)
                if defn_res.is_ok
                else None
            )
            input_payload = await uow.payloads.resolve_step_input(
                tenant_id=run.tenant_id, step_run_id=step.id
            )
            return run, step, node, input_payload

    async def _try_reconcile_effect(
        self,
        *,
        run: WorkflowRun,
        step: StepRun,
        node: NodeDefinition | None,
        lease: ActiveLease,
        input_payload: JsonDict,
    ) -> ReconcileOutcome[JsonDict] | None:
        if (
            node is None
            or node.effect_policy != EffectPolicy.RECONCILABLE_EFFECT
            or self._handler_registry is None
        ):
            return None

        handler_res = self._handler_registry.get(node.step_type)
        if handler_res.is_err:
            return None
        handler = handler_res.unwrap()
        if not isinstance(handler, ReconcilableStepHandlerPort):
            return None

        ctx = StepContext(
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
        reconcile_res = await handler.reconcile(ctx, input_payload)
        if reconcile_res.is_err:
            return None
        return reconcile_res.unwrap()


__all__ = [
    "ReapExpiredLeasesCommand",
    "ReapExpiredLeasesResultDTO",
    "ReapExpiredLeasesUseCase",
]
