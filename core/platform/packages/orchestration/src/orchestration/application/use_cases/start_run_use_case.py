"""Use case for starting a new durable WorkflowRun."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from observability import ObservabilityProvider
from seedwork.domain.types import JsonDict

from orchestration.application.services.step_scheduler_service import (
    WorkflowStepSchedulerService,
)
from orchestration.domain.constants import (
    ConditionKind,
    IdempotencyEvictionPolicy,
    MatchAction,
    MatchKind,
    PayloadType,
    Priority,
    QueueItemKind,
    RunStatus,
    StepStatus,
)
from orchestration.domain.definition import WorkflowDefinition
from orchestration.domain.exceptions import (
    DuplicateIdempotencyKeyError,
    Result,
    WorkflowError,
)
from orchestration.domain.matching import DagMatchCompiler, WorkflowMatch
from orchestration.domain.run import PayloadRecord, WorkflowRun
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from orchestration.ports.outbound.repository_ports import WorkflowUnitOfWorkPort

logger = ObservabilityProvider.logger(__name__)


@dataclass(frozen=True, kw_only=True)
class StartRunCommand:
    """Immutable command DTO to start a durable workflow execution."""

    tenant_id: str
    workflow_id: str
    workflow_version: int
    idempotency_key: str
    input_payload: JsonDict
    trace_id: str
    correlation_id: str | None = None
    concurrency_key: str | None = None
    priority: Priority | None = None
    parent_run_id: str | None = None
    idempotency_eviction_policy: IdempotencyEvictionPolicy = IdempotencyEvictionPolicy.TTL
    idempotency_ttl: timedelta = timedelta(hours=24)
    deduplicate_if_exists: bool = False
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class StartRunResultDTO:
    """Result DTO returned when a WorkflowRun is started or deduplicated."""

    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    status: RunStatus
    was_deduplicated: bool = False


class StartRunUseCase:
    """Validates workflow definition, claims cross-partition idempotency key, stores zero-copy payloads,
    compiles Hatchet CNF matches, and schedules root steps.
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

    async def execute(self, command: StartRunCommand) -> Result[StartRunResultDTO, WorkflowError]:
        defn_res = self._definition_registry.get(command.workflow_id, command.workflow_version)
        if defn_res.is_err:
            return Result.err(defn_res.unwrap_err())
        definition = defn_res.unwrap()

        run = WorkflowRun.create(
            tenant_id=command.tenant_id,
            definition=definition,
            idempotency_key=command.idempotency_key,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            concurrency_key=command.concurrency_key,
            priority=command.priority,
            parent_run_id=command.parent_run_id,
            now=command.now,
        )

        async with self._uow_factory() as uow:
            claim_res = await uow.idempotency.try_claim_key(
                tenant_id=command.tenant_id,
                workflow_id=command.workflow_id,
                key=command.idempotency_key,
                run_id=run.id,
                eviction_policy=command.idempotency_eviction_policy,
                ttl=command.idempotency_ttl,
                now=command.now,
            )
            if claim_res.is_err:
                return await self._handle_duplicate_idempotency(
                    uow=uow,
                    command=command,
                    dup_err=claim_res.unwrap_err(),
                )

            await self._persist_run_and_payloads(
                uow=uow,
                run=run,
                definition=definition,
                input_payload=command.input_payload,
            )
            await self._compile_and_schedule_initial_graph(
                uow=uow,
                run=run,
                definition=definition,
                now=command.now,
            )

            refreshed_res = await uow.runs.get_by_id(run.tenant_id, run.id)
            final_run = refreshed_res.unwrap() if refreshed_res.is_ok else run
            await uow.commit()

        logger.info(
            "workflow_run_started",
            tenant_id=final_run.tenant_id,
            run_id=final_run.id,
            workflow_id=final_run.workflow_id,
            workflow_version=final_run.workflow_version,
            status=final_run.status.value,
        )

        return Result.ok(
            StartRunResultDTO(
                run_id=final_run.id,
                tenant_id=final_run.tenant_id,
                workflow_id=final_run.workflow_id,
                workflow_version=final_run.workflow_version,
                status=final_run.status,
                was_deduplicated=False,
            )
        )

    @staticmethod
    async def _handle_duplicate_idempotency(
        *,
        uow: WorkflowUnitOfWorkPort,
        command: StartRunCommand,
        dup_err: DuplicateIdempotencyKeyError,
    ) -> Result[StartRunResultDTO, WorkflowError]:
        if command.deduplicate_if_exists and dup_err.existing_run_id:
            existing_res = await uow.runs.get_by_id(command.tenant_id, dup_err.existing_run_id)
            if existing_res.is_ok:
                existing_run = existing_res.unwrap()
                return Result.ok(
                    StartRunResultDTO(
                        run_id=existing_run.id,
                        tenant_id=existing_run.tenant_id,
                        workflow_id=existing_run.workflow_id,
                        workflow_version=existing_run.workflow_version,
                        status=existing_run.status,
                        was_deduplicated=True,
                    )
                )
        return Result.err(dup_err)

    @staticmethod
    async def _persist_run_and_payloads(
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        input_payload: JsonDict,
    ) -> None:
        await uow.runs.save(run)
        await uow.payloads.save_payload(
            PayloadRecord.create_inline(
                tenant_id=run.tenant_id,
                owner_id=run.id,
                owner_created_at=run.created_at,
                payload_type=PayloadType.RUN_INPUT,
                content=input_payload,
            )
        )
        for root_node in definition.root_nodes():
            root_step = run.steps[root_node.node_key]
            await uow.payloads.save_payload(
                PayloadRecord.create_reference(
                    tenant_id=run.tenant_id,
                    owner_id=root_step.id,
                    owner_created_at=root_step.created_at,
                    payload_type=PayloadType.STEP_INPUT,
                    reference_owner_id=run.id,
                    reference_created_at=run.created_at,
                )
            )

    async def _compile_and_schedule_initial_graph(
        self,
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        now: datetime,
    ) -> None:
        step_ids_by_node_key = {
            node_key: (step.id, step.created_at) for node_key, step in run.steps.items()
        }
        initial_matches = DagMatchCompiler.compile_initial_matches(
            tenant_id=run.tenant_id,
            run_id=run.id,
            definition=definition,
            step_ids_by_node_key=step_ids_by_node_key,
            now=now,
        )
        if initial_matches:
            await uow.matches.save_matches(initial_matches)
            await self._enqueue_root_signal_timers(
                uow=uow,
                run=run,
                definition=definition,
                matches=initial_matches,
            )

        for root_node in definition.root_nodes():
            root_step = run.steps[root_node.node_key]
            if root_step.status == StepStatus.READY:
                await self._step_scheduler.schedule_ready_step(
                    uow=uow,
                    run=run,
                    step=root_step,
                    definition=definition,
                    node=root_node,
                    available_at=now,
                    now=now,
                )

    @staticmethod
    async def _enqueue_root_signal_timers(
        *,
        uow: WorkflowUnitOfWorkPort,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        matches: Sequence[WorkflowMatch],
    ) -> None:
        for match in matches:
            if match.kind != MatchKind.SIGNAL_WAIT:
                continue
            node = definition.get_node(match.node_key)
            queue_name = node.queue_name if node is not None else "default"
            for cond in match.conditions:
                if cond.condition_kind == ConditionKind.SLEEP and cond.timeout_at is not None:
                    item_kind = (
                        QueueItemKind.SLEEP_WAKE
                        if cond.action == MatchAction.QUEUE
                        else QueueItemKind.WAIT_TIMEOUT
                    )
                    await uow.queue.enqueue(
                        tenant_id=run.tenant_id,
                        run_id=run.id,
                        step_run_id=match.step_run_id,
                        step_created_at=match.step_created_at,
                        retry_count=0,
                        item_kind=item_kind,
                        queue_name=queue_name,
                        priority=run.priority,
                        available_at=cond.timeout_at,
                        concurrency_key=run.concurrency_key,
                    )


__all__ = ["StartRunCommand", "StartRunResultDTO", "StartRunUseCase"]
