"""Summary and query response DTOs for Stitch use cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.run import StepRun, WorkflowRun
from seedwork.domain.types import JsonPrimitive

from ip.engine.domain.stitch.stitch import Stitch


@dataclass(frozen=True)
class StitchNodeSummaryDTO:
    """Pure boundary DTO representing a static node in a Stitch WorkflowDefinition."""

    node_key: str
    kind: str
    step_type: str
    parents: tuple[str, ...]
    edge_condition: str
    effect_policy: str
    wait_event_key: str | None
    queue_name: str


@dataclass(frozen=True)
class StitchDefinitionSummaryDTO:
    """Pure boundary DTO representing a registered Stitch WorkflowDefinition DAG."""

    workflow_id: str
    version: int
    default_priority: str
    description: str
    nodes: tuple[StitchNodeSummaryDTO, ...]


@dataclass(frozen=True)
class StitchSummaryDTO:
    """Pure boundary DTO representing a Stitch."""

    id: str
    tenant_id: str
    canonical_event_type: str
    target_workflow_id: str
    name: str = ""
    description: str = ""
    mapping_spec_id: str | None = None
    filter_conditions: Mapping[str, JsonPrimitive] = field(default_factory=dict)
    is_active: bool = True


@dataclass(frozen=True)
class StitchStepRunSummaryDTO:
    """Pure boundary DTO representing a StepRun inside a WorkflowRun."""

    step_run_id: str
    node_key: str
    status: str
    retry_count: int
    app_retry_count: int
    internal_retry_count: int
    iteration_count: int
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class StitchRunSummaryDTO:
    """Pure boundary DTO representing a durable Stitch WorkflowRun and its steps."""

    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    status: str
    priority: str
    concurrency_key: str | None
    idempotency_key: str
    trace_id: str
    correlation_id: str | None
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: tuple[StitchStepRunSummaryDTO, ...]


def to_node_dto(node: NodeDefinition) -> StitchNodeSummaryDTO:
    return StitchNodeSummaryDTO(
        node_key=node.node_key,
        kind=node.kind.value,
        step_type=node.step_type,
        parents=node.parents,
        edge_condition=node.edge_condition.value,
        effect_policy=node.effect_policy.value,
        wait_event_key=node.wait_event.event_key if node.wait_event is not None else None,
        queue_name=node.queue_name,
    )


def to_definition_dto(defn: WorkflowDefinition) -> StitchDefinitionSummaryDTO:
    return StitchDefinitionSummaryDTO(
        workflow_id=defn.workflow_id,
        version=defn.version,
        default_priority=defn.default_priority.name,
        description=defn.description,
        nodes=tuple(to_node_dto(n) for n in defn.nodes),
    )


def to_stitch_dto(stitch: Stitch) -> StitchSummaryDTO:
    return StitchSummaryDTO(
        id=stitch.id,
        tenant_id=stitch.tenant_id,
        canonical_event_type=stitch.canonical_event_type,
        target_workflow_id=stitch.target_workflow_id,
        name=stitch.name,
        description=stitch.description,
        mapping_spec_id=stitch.mapping_spec_id,
        filter_conditions=dict(stitch.filter_conditions),
        is_active=stitch.is_active,
    )


def to_step_dto(step: StepRun) -> StitchStepRunSummaryDTO:
    return StitchStepRunSummaryDTO(
        step_run_id=step.id,
        node_key=step.node_key,
        status=step.status.value,
        retry_count=step.retry_count,
        app_retry_count=step.app_retry_count,
        internal_retry_count=step.internal_retry_count,
        iteration_count=step.iteration_count,
        failure_code=step.failure_code,
        failure_detail=step.failure_detail,
        created_at=step.created_at,
        finished_at=step.finished_at,
    )


def to_run_dto(run: WorkflowRun) -> StitchRunSummaryDTO:
    steps = tuple(to_step_dto(s) for s in run.steps.values())
    return StitchRunSummaryDTO(
        run_id=run.id,
        tenant_id=run.tenant_id,
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        status=run.status.value,
        priority=run.priority.name,
        concurrency_key=run.concurrency_key,
        idempotency_key=run.idempotency_key,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        steps=steps,
    )


__all__ = [
    "StitchDefinitionSummaryDTO",
    "StitchNodeSummaryDTO",
    "StitchRunSummaryDTO",
    "StitchStepRunSummaryDTO",
    "StitchSummaryDTO",
    "to_definition_dto",
    "to_node_dto",
    "to_run_dto",
    "to_step_dto",
    "to_stitch_dto",
]
