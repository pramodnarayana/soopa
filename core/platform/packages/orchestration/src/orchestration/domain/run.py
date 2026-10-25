"""WorkflowRun aggregate root, StepRun entity (with Hatchet 3-counter retries), ActiveLease, and PayloadRecord."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.models import AggregateRoot
from seedwork.utils import generate_id

from orchestration.domain.constants import (
    AttemptStatus,
    IdempotencyEvictionPolicy,
    NodeKind,
    PayloadLocation,
    PayloadType,
    Priority,
    RunStatus,
    StepFailureCode,
    StepStatus,
)
from orchestration.domain.definition import WorkflowDefinition
from orchestration.domain.events import (
    WorkflowRunCancelledEvent,
    WorkflowRunFailedEvent,
    WorkflowRunStartedEvent,
    WorkflowRunSucceededEvent,
    WorkflowStepFailedEvent,
    WorkflowStepReadyEvent,
    WorkflowStepRetryScheduledEvent,
    WorkflowStepSkippedEvent,
    WorkflowStepStartedEvent,
    WorkflowStepSucceededEvent,
    WorkflowStepTimedOutEvent,
    WorkflowStepWaitingEvent,
)
from orchestration.domain.exceptions import (
    FencingTokenMismatchError,
    InvalidTransitionError,
    Result,
    StepNotFoundError,
    WorkflowError,
)


@dataclass(frozen=True)
class ActiveLease:
    """Unpartitioned active lease row (Hatchet v1_task_runtime / workflow_active_leases)."""

    step_run_id: str
    step_created_at: datetime
    retry_count: int
    run_id: str
    tenant_id: str
    worker_id: str
    lease_expires_at: datetime
    timeout_at: datetime
    evicted_at: datetime | None = None

    def is_lease_expired(self, now: datetime) -> bool:
        return now >= self.lease_expires_at

    def is_timed_out(self, now: datetime) -> bool:
        return now >= self.timeout_at


@dataclass(frozen=True)
class StepAttempt:
    """Immutable audit record of a single execution attempt of a StepRun."""

    id: str
    step_run_id: str
    tenant_id: str
    retry_count: int
    app_retry_count: int
    internal_retry_count: int
    worker_id: str
    status: AttemptStatus
    is_app_error: bool | None = None
    outcome_code: str | None = None
    outcome_detail: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


@dataclass(frozen=True)
class PayloadRecord:
    """Decoupled payload record with zero-copy reference and S3 offload support (Hatchet v1_payload)."""

    tenant_id: str
    owner_id: str
    owner_created_at: datetime
    payload_type: PayloadType
    location: PayloadLocation
    inline_content: JsonDict | None = None
    external_ref: str | None = None
    payload_reference_id: str | None = None
    payload_reference_created_at: datetime | None = None
    size_bytes: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create_inline(
        cls,
        *,
        tenant_id: str,
        owner_id: str,
        owner_created_at: datetime,
        payload_type: PayloadType,
        content: JsonDict,
        size_bytes: int = 0,
    ) -> PayloadRecord:
        return cls(
            tenant_id=tenant_id,
            owner_id=owner_id,
            owner_created_at=owner_created_at,
            payload_type=payload_type,
            location=PayloadLocation.INLINE,
            inline_content=dict(content),
            size_bytes=size_bytes,
        )

    @classmethod
    def create_reference(
        cls,
        *,
        tenant_id: str,
        owner_id: str,
        owner_created_at: datetime,
        payload_type: PayloadType,
        reference_owner_id: str,
        reference_created_at: datetime,
    ) -> PayloadRecord:
        """Zero-copy reference pointing a root step's STEP_INPUT to the parent run's RUN_INPUT."""
        return cls(
            tenant_id=tenant_id,
            owner_id=owner_id,
            owner_created_at=owner_created_at,
            payload_type=payload_type,
            location=PayloadLocation.REFERENCE,
            payload_reference_id=reference_owner_id,
            payload_reference_created_at=reference_created_at,
        )


@dataclass(frozen=True)
class IdempotencyKeyRecord:
    """Unpartitioned cross-partition idempotency claim (Hatchet v1_idempotency_key)."""

    tenant_id: str
    workflow_id: str
    key: str
    claimed_by_run_id: str
    eviction_policy: IdempotencyEvictionPolicy
    expires_at: datetime
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(kw_only=True)
class StepRun:
    """Mutable step node entity managed exclusively through its parent WorkflowRun aggregate."""

    id: str
    run_id: str
    run_created_at: datetime
    tenant_id: str
    node_key: str
    status: StepStatus
    retry_count: int = 0
    app_retry_count: int = 0
    internal_retry_count: int = 0
    failure_code: str | None = None
    failure_detail: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            StepStatus.SUCCEEDED,
            StepStatus.FAILED,
            StepStatus.TIMED_OUT,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        )


@dataclass(kw_only=True, eq=False)
class WorkflowRun(AggregateRoot):
    """Aggregate root governing the state machine of a durable workflow execution."""

    ID_PREFIX: ClassVar[str] = SystemIdPrefix.WORKFLOW_RUN.value

    id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    status: RunStatus
    priority: Priority
    concurrency_key: str | None = None
    idempotency_key: str
    parent_run_id: str | None = None
    trace_id: str
    correlation_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: dict[str, StepRun] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        definition: WorkflowDefinition,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str | None = None,
        concurrency_key: str | None = None,
        priority: Priority | None = None,
        parent_run_id: str | None = None,
        now: datetime | None = None,
    ) -> WorkflowRun:
        timestamp = now or datetime.now(UTC)
        run_id = generate_id(cls.ID_PREFIX)
        resolved_priority = priority or definition.default_priority

        steps: dict[str, StepRun] = {}
        for node in definition.nodes:
            is_root = len(node.parents) == 0
            is_wait_or_sleep = node.kind in (NodeKind.SLEEP, NodeKind.WAIT_FOR_EVENT)
            if is_root and is_wait_or_sleep:
                initial_status = StepStatus.WAITING
            elif is_root:
                initial_status = StepStatus.READY
            else:
                initial_status = StepStatus.PENDING

            step_id = generate_id(SystemIdPrefix.WORKFLOW_STEP.value)
            steps[node.node_key] = StepRun(
                id=step_id,
                run_id=run_id,
                run_created_at=timestamp,
                tenant_id=tenant_id,
                node_key=node.node_key,
                status=initial_status,
                created_at=timestamp,
            )

        initial_run_status = (
            RunStatus.WAITING
            if all(s.status in (StepStatus.WAITING, StepStatus.PENDING) for s in steps.values())
            and any(s.status == StepStatus.WAITING for s in steps.values())
            else RunStatus.QUEUED
        )

        run = cls(
            id=run_id,
            tenant_id=tenant_id,
            workflow_id=definition.workflow_id,
            workflow_version=definition.version,
            status=initial_run_status,
            priority=resolved_priority,
            concurrency_key=concurrency_key,
            idempotency_key=idempotency_key,
            parent_run_id=parent_run_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            created_at=timestamp,
            steps=steps,
        )
        run.add_domain_event(
            WorkflowRunStartedEvent(
                run_id=run.id,
                tenant_id=run.tenant_id,
                workflow_id=run.workflow_id,
                workflow_version=run.workflow_version,
                trace_id=run.trace_id,
                correlation_id=run.correlation_id,
            )
        )
        for step in steps.values():
            if step.status == StepStatus.READY:
                run.add_domain_event(
                    WorkflowStepReadyEvent(
                        run_id=run.id,
                        step_run_id=step.id,
                        tenant_id=run.tenant_id,
                        node_key=step.node_key,
                        retry_count=step.retry_count,
                        trace_id=run.trace_id,
                        correlation_id=run.correlation_id,
                    )
                )
            elif step.status == StepStatus.WAITING:
                run.add_domain_event(
                    WorkflowStepWaitingEvent(
                        run_id=run.id,
                        step_run_id=step.id,
                        tenant_id=run.tenant_id,
                        node_key=step.node_key,
                        trace_id=run.trace_id,
                        correlation_id=run.correlation_id,
                    )
                )
        return run

    def get_step(self, node_key: str) -> Result[StepRun, StepNotFoundError]:
        step = self.steps.get(node_key)
        if step is None:
            return Result.err(StepNotFoundError.for_node(self.id, node_key))
        return Result.ok(step)

    def mark_step_ready(self, node_key: str) -> Result[StepRun, WorkflowError]:
        """Transition a PENDING, WAITING, or RETRY_SCHEDULED step to READY."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()
        if step.status not in (
            StepStatus.PENDING,
            StepStatus.WAITING,
            StepStatus.RETRY_SCHEDULED,
        ):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="mark_step_ready",
                )
            )
        step.status = StepStatus.READY
        if self.status == RunStatus.WAITING:
            self.status = RunStatus.RUNNING
        self.add_domain_event(
            WorkflowStepReadyEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(step)

    def mark_step_waiting(self, node_key: str) -> Result[StepRun, WorkflowError]:
        """Transition a PENDING or READY step to WAITING (e.g. stage-2 SLEEP or WAIT_FOR_EVENT)."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()
        if step.status not in (StepStatus.PENDING, StepStatus.READY):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="mark_step_waiting",
                )
            )
        step.status = StepStatus.WAITING
        self.add_domain_event(
            WorkflowStepWaitingEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        self._recompute_run_status()
        return Result.ok(step)

    def claim_step(
        self,
        *,
        node_key: str,
        worker_id: str,
        lease_ttl: timedelta = timedelta(seconds=30),
        step_timeout: timedelta = timedelta(minutes=5),
        now: datetime | None = None,
    ) -> Result[tuple[StepAttempt, ActiveLease], WorkflowError]:
        """Claim a READY step for execution, creating an ActiveLease and StepAttempt."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return Result.err(step_res.unwrap_err())
        step = step_res.unwrap()

        if step.status != StepStatus.READY:
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="claim_step",
                )
            )

        timestamp = now or datetime.now(UTC)
        step.status = StepStatus.RUNNING
        if self.status in (RunStatus.QUEUED, RunStatus.WAITING):
            self.status = RunStatus.RUNNING
            if self.started_at is None:
                self.started_at = timestamp

        attempt = StepAttempt(
            id=generate_id(SystemIdPrefix.WORKFLOW_ATTEMPT.value),
            step_run_id=step.id,
            tenant_id=self.tenant_id,
            retry_count=step.retry_count,
            app_retry_count=step.app_retry_count,
            internal_retry_count=step.internal_retry_count,
            worker_id=worker_id,
            status=AttemptStatus.RUNNING,
            started_at=timestamp,
        )
        lease = ActiveLease(
            step_run_id=step.id,
            step_created_at=step.created_at,
            retry_count=step.retry_count,
            run_id=self.id,
            tenant_id=self.tenant_id,
            worker_id=worker_id,
            lease_expires_at=timestamp + lease_ttl,
            timeout_at=timestamp + step_timeout,
        )
        self.add_domain_event(
            WorkflowStepStartedEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                worker_id=worker_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok((attempt, lease))

    def complete_step(
        self,
        *,
        node_key: str,
        fencing_retry_count: int,
        now: datetime | None = None,
    ) -> Result[StepRun, WorkflowError]:
        """Complete a RUNNING or WAITING step, verifying the fencing retry_count token."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.retry_count != fencing_retry_count:
            return Result.err(
                FencingTokenMismatchError.for_step(
                    step_run_id=step.id,
                    expected_retry_count=step.retry_count,
                    actual_retry_count=fencing_retry_count,
                )
            )

        if step.status not in (StepStatus.RUNNING, StepStatus.WAITING, StepStatus.READY):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="complete_step",
                )
            )

        timestamp = now or datetime.now(UTC)
        step.status = StepStatus.SUCCEEDED
        step.finished_at = timestamp
        step.failure_code = None
        step.failure_detail = None

        self.add_domain_event(
            WorkflowStepSucceededEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        self._recompute_run_status(now=timestamp)
        return Result.ok(step)

    def schedule_step_retry(
        self,
        *,
        node_key: str,
        fencing_retry_count: int,
        failure_code: StepFailureCode,
        failure_detail: str,
        delay: timedelta,
        is_app_error: bool,
        is_rate_limit_park: bool = False,
    ) -> Result[StepRun, WorkflowError]:
        """Schedule a retry or rate-limit park using Hatchet's 3-counter retry invariant:
        - Rate-limit park (`is_rate_limit_park=True`): preserves `retry_count`, `app_retry_count`, and `internal_retry_count`.
        - Application error (`is_app_error=True`): increments `retry_count` (fencing token) AND `app_retry_count`.
        - Internal/worker crash (`is_app_error=False`): increments `retry_count` (fencing token) AND `internal_retry_count` (never burning user retries).
        """
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.retry_count != fencing_retry_count:
            return Result.err(
                FencingTokenMismatchError.for_step(
                    step_run_id=step.id,
                    expected_retry_count=step.retry_count,
                    actual_retry_count=fencing_retry_count,
                )
            )

        if step.status != StepStatus.RUNNING:
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="schedule_step_retry",
                )
            )

        if not is_rate_limit_park:
            step.retry_count += 1
            if is_app_error:
                step.app_retry_count += 1
            else:
                step.internal_retry_count += 1

        step.status = StepStatus.RETRY_SCHEDULED
        step.failure_code = failure_code.value
        step.failure_detail = failure_detail

        self.add_domain_event(
            WorkflowStepRetryScheduledEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                app_retry_count=step.app_retry_count,
                internal_retry_count=step.internal_retry_count,
                failure_code=failure_code.value,
                delay_seconds=delay.total_seconds(),
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(step)

    def fail_step_terminally(
        self,
        *,
        node_key: str,
        fencing_retry_count: int,
        failure_code: StepFailureCode,
        failure_detail: str,
        now: datetime | None = None,
    ) -> Result[StepRun, WorkflowError]:
        """Transition a RUNNING step to FAILED when a terminal error occurs or retries are exhausted."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.retry_count != fencing_retry_count:
            return Result.err(
                FencingTokenMismatchError.for_step(
                    step_run_id=step.id,
                    expected_retry_count=step.retry_count,
                    actual_retry_count=fencing_retry_count,
                )
            )

        if step.status != StepStatus.RUNNING:
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="fail_step_terminally",
                )
            )

        timestamp = now or datetime.now(UTC)
        step.status = StepStatus.FAILED
        step.failure_code = failure_code.value
        step.failure_detail = failure_detail
        step.finished_at = timestamp

        self.add_domain_event(
            WorkflowStepFailedEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                failure_code=failure_code.value,
                failure_detail=failure_detail,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(step)

    def timeout_step(
        self,
        *,
        node_key: str,
        now: datetime | None = None,
    ) -> Result[StepRun, WorkflowError]:
        """Transition a WAITING or RUNNING step to TIMED_OUT."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.status not in (StepStatus.WAITING, StepStatus.RUNNING):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="timeout_step",
                )
            )

        timestamp = now or datetime.now(UTC)
        step.status = StepStatus.TIMED_OUT
        step.failure_code = StepFailureCode.TIMEOUT.value
        step.failure_detail = "Step wait or execution timed out."
        step.finished_at = timestamp

        self.add_domain_event(
            WorkflowStepTimedOutEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(step)

    def skip_step(
        self,
        *,
        node_key: str,
        now: datetime | None = None,
    ) -> Result[StepRun, WorkflowError]:
        """Transition a PENDING or READY step to SKIPPED."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.status not in (StepStatus.PENDING, StepStatus.READY):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="skip_step",
                )
            )

        timestamp = now or datetime.now(UTC)
        step.status = StepStatus.SKIPPED
        step.finished_at = timestamp
        self.add_domain_event(
            WorkflowStepSkippedEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        self._recompute_run_status(now=timestamp)
        return Result.ok(step)

    def cancel_step(
        self,
        *,
        node_key: str,
        reason: str = "Parent failed or cancelled",
        now: datetime | None = None,
    ) -> Result[StepRun, WorkflowError]:
        """Cancel a non-terminal step due to upstream failure or run cancellation."""
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()
        if step.is_terminal:
            return Result.ok(step)

        timestamp = now or datetime.now(UTC)
        step.status = StepStatus.CANCELLED
        step.failure_detail = reason
        step.finished_at = timestamp
        return Result.ok(step)

    def replay_from_failed_step(
        self,
        *,
        node_key: str,
    ) -> Result[StepRun, WorkflowError]:
        """Operator action (Hatchet ReplayTasks):
        Increments `retry_count` by 1 (fencing any late messages from prior attempts)
        while resetting `app_retry_count = 0` and `internal_retry_count = 0`.
        """
        if self.status not in (RunStatus.FAILED, RunStatus.CANCELLED):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="WorkflowRun",
                    entity_id=self.id,
                    current_status=self.status.value,
                    attempted_action="replay_from_failed_step",
                )
            )
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.status not in (
            StepStatus.FAILED,
            StepStatus.TIMED_OUT,
            StepStatus.CANCELLED,
        ):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="replay_from_failed_step",
                )
            )

        step.retry_count += 1
        step.app_retry_count = 0
        step.internal_retry_count = 0
        step.status = StepStatus.READY
        step.failure_code = None
        step.failure_detail = None
        step.finished_at = None

        for other in self.steps.values():
            if other.id != step.id and other.status == StepStatus.CANCELLED:
                other.status = StepStatus.PENDING
                other.failure_detail = None
                other.finished_at = None

        self.status = RunStatus.QUEUED
        self.failure_code = None
        self.failure_detail = None
        self.finished_at = None

        self.add_domain_event(
            WorkflowStepReadyEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(step)

    def skip_failed_step_by_operator(
        self,
        *,
        node_key: str,
        reason: str,
        now: datetime | None = None,
    ) -> Result[StepRun, WorkflowError]:
        """Operator action (SkipFailedStep):
        Marks a FAILED or TIMED_OUT step as SUCCEEDED (with manual output persisted in the payload store)
        and re-opens the run so downstream DAG children can proceed.
        """
        if self.status not in (RunStatus.FAILED, RunStatus.RUNNING, RunStatus.WAITING):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="WorkflowRun",
                    entity_id=self.id,
                    current_status=self.status.value,
                    attempted_action="skip_failed_step_by_operator",
                )
            )
        step_res = self.get_step(node_key)
        if step_res.is_err:
            return step_res
        step = step_res.unwrap()

        if step.status not in (StepStatus.FAILED, StepStatus.TIMED_OUT):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="StepRun",
                    entity_id=step.id,
                    current_status=step.status.value,
                    attempted_action="skip_failed_step_by_operator",
                )
            )

        timestamp = now or datetime.now(UTC)
        step.retry_count += 1
        step.status = StepStatus.SUCCEEDED
        step.failure_code = None
        step.failure_detail = reason
        step.finished_at = timestamp

        for other in self.steps.values():
            if other.id != step.id and other.status == StepStatus.CANCELLED:
                other.status = StepStatus.PENDING
                other.failure_detail = None
                other.finished_at = None

        self.status = RunStatus.RUNNING
        self.failure_code = None
        self.failure_detail = None
        self.finished_at = None

        self.add_domain_event(
            WorkflowStepSucceededEvent(
                run_id=self.id,
                step_run_id=step.id,
                tenant_id=self.tenant_id,
                node_key=step.node_key,
                retry_count=step.retry_count,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        self._recompute_run_status(now=timestamp)
        return Result.ok(step)

    def cancel_run(
        self,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> Result[WorkflowRun, WorkflowError]:
        """Cancel the entire WorkflowRun and all non-terminal steps."""
        if self.status in (RunStatus.SUCCEEDED, RunStatus.CANCELLED):
            return Result.err(
                InvalidTransitionError.for_entity(
                    entity_type="WorkflowRun",
                    entity_id=self.id,
                    current_status=self.status.value,
                    attempted_action="cancel_run",
                )
            )
        timestamp = now or datetime.now(UTC)
        for step in self.steps.values():
            if not step.is_terminal:
                step.status = StepStatus.CANCELLED
                step.failure_detail = reason
                step.finished_at = timestamp

        self.status = RunStatus.CANCELLED
        self.failure_detail = reason
        self.finished_at = timestamp
        self.add_domain_event(
            WorkflowRunCancelledEvent(
                run_id=self.id,
                tenant_id=self.tenant_id,
                workflow_id=self.workflow_id,
                workflow_version=self.workflow_version,
                reason=reason,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
            )
        )
        return Result.ok(self)

    def finalize_after_match_propagation(self, now: datetime | None = None) -> None:
        """Re-evaluate overall WorkflowRun status after DAG match propagation settles."""
        self._recompute_run_status(now=now)

    def _recompute_run_status(self, now: datetime | None = None) -> None:
        if self.status in (
            RunStatus.CANCELLED,
            RunStatus.BLOCKED_VERSION_UNAVAILABLE,
        ):
            return

        timestamp = now or datetime.now(UTC)
        all_steps = list(self.steps.values())

        if all(s.is_terminal for s in all_steps):
            failed_steps = [
                s
                for s in all_steps
                if s.status in (StepStatus.FAILED, StepStatus.TIMED_OUT)
            ]
            if not failed_steps:
                self.status = RunStatus.SUCCEEDED
                self.finished_at = timestamp
                self.add_domain_event(
                    WorkflowRunSucceededEvent(
                        run_id=self.id,
                        tenant_id=self.tenant_id,
                        workflow_id=self.workflow_id,
                        workflow_version=self.workflow_version,
                        trace_id=self.trace_id,
                        correlation_id=self.correlation_id,
                    )
                )
            else:
                primary_fail = failed_steps[0]
                self.status = RunStatus.FAILED
                self.failure_code = primary_fail.failure_code or StepFailureCode.UNHANDLED_EXCEPTION.value
                self.failure_detail = primary_fail.failure_detail or "Workflow step failed."
                self.finished_at = timestamp
                self.add_domain_event(
                    WorkflowRunFailedEvent(
                        run_id=self.id,
                        tenant_id=self.tenant_id,
                        workflow_id=self.workflow_id,
                        workflow_version=self.workflow_version,
                        failure_code=self.failure_code,
                        failure_detail=self.failure_detail,
                        trace_id=self.trace_id,
                        correlation_id=self.correlation_id,
                    )
                )
            return

        active_non_pending = [
            s
            for s in all_steps
            if not s.is_terminal and s.status != StepStatus.PENDING
        ]
        if active_non_pending and all(
            s.status == StepStatus.WAITING for s in active_non_pending
        ):
            self.status = RunStatus.WAITING
        elif self.status == RunStatus.WAITING and any(
            s.status in (StepStatus.RUNNING, StepStatus.READY, StepStatus.RETRY_SCHEDULED)
            for s in all_steps
        ):
            self.status = RunStatus.RUNNING


__all__ = [
    "ActiveLease",
    "IdempotencyKeyRecord",
    "PayloadRecord",
    "StepAttempt",
    "StepRun",
    "WorkflowRun",
]
