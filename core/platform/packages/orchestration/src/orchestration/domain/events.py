"""Pure frozen domain events emitted by the Durable Workflow Engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class WorkflowDomainEvent(DomainEvent):
    """Base tenant-routed domain event for the Durable Workflow Engine."""

    tenant_id: str

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True, kw_only=True)
class WorkflowRunStartedEvent(WorkflowDomainEvent):
    """Emitted when a WorkflowRun transitions to QUEUED or RUNNING."""

    run_id: str
    workflow_id: str
    workflow_version: int
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.run.started", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowRunSucceededEvent(WorkflowDomainEvent):
    """Emitted when all terminal nodes of a WorkflowRun complete."""

    run_id: str
    workflow_id: str
    workflow_version: int
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.run.succeeded", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowRunFailedEvent(WorkflowDomainEvent):
    """Emitted when a WorkflowRun reaches a terminal FAILED or BLOCKED state."""

    run_id: str
    workflow_id: str
    workflow_version: int
    failure_code: str
    failure_detail: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.run.failed", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowRunCancelledEvent(WorkflowDomainEvent):
    """Emitted when a WorkflowRun is cancelled by an operator or superseded by concurrency policy."""

    run_id: str
    workflow_id: str
    workflow_version: int
    reason: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.run.cancelled", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepReadyEvent(WorkflowDomainEvent):
    """Emitted when a StepRun's CNF match conditions are satisfied and it becomes READY."""

    run_id: str
    step_run_id: str
    node_key: str
    retry_count: int
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.ready", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepStartedEvent(WorkflowDomainEvent):
    """Emitted when a worker claims a StepRun and acquires an active lease."""

    run_id: str
    step_run_id: str
    node_key: str
    retry_count: int
    worker_id: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.started", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepSucceededEvent(WorkflowDomainEvent):
    """Emitted when a StepRun completes with a valid fencing token."""

    run_id: str
    step_run_id: str
    node_key: str
    retry_count: int
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.succeeded", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepRetryScheduledEvent(WorkflowDomainEvent):
    """Emitted when a StepRun schedules a retry or rate-limit requeue."""

    run_id: str
    step_run_id: str
    node_key: str
    retry_count: int
    app_retry_count: int
    internal_retry_count: int
    failure_code: str
    delay_seconds: float
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.retry_scheduled", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepFailedEvent(WorkflowDomainEvent):
    """Emitted when a StepRun fails terminally or exhausts its retry budget."""

    run_id: str
    step_run_id: str
    node_key: str
    retry_count: int
    failure_code: str
    failure_detail: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.failed", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepWaitingEvent(WorkflowDomainEvent):
    """Emitted when a WAIT_FOR_EVENT or SLEEP StepRun enters WAITING."""

    run_id: str
    step_run_id: str
    node_key: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.waiting", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepTimedOutEvent(WorkflowDomainEvent):
    """Emitted when a StepRun or wait condition times out."""

    run_id: str
    step_run_id: str
    node_key: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.timed_out", init=False)


@dataclass(frozen=True, kw_only=True)
class WorkflowStepSkippedEvent(WorkflowDomainEvent):
    """Emitted when a StepRun is skipped due to branch evaluation or parent skip propagation."""

    run_id: str
    step_run_id: str
    node_key: str
    trace_id: str
    correlation_id: str | None = None
    event_name: str = field(default="workflow.step.skipped", init=False)


__all__ = [
    "WorkflowDomainEvent",
    "WorkflowRunCancelledEvent",
    "WorkflowRunFailedEvent",
    "WorkflowRunStartedEvent",
    "WorkflowRunSucceededEvent",
    "WorkflowStepFailedEvent",
    "WorkflowStepReadyEvent",
    "WorkflowStepRetryScheduledEvent",
    "WorkflowStepSkippedEvent",
    "WorkflowStepStartedEvent",
    "WorkflowStepSucceededEvent",
    "WorkflowStepTimedOutEvent",
    "WorkflowStepWaitingEvent",
]
