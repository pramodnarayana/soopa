"""Pydantic HTTP request and response DTOs for Layer-4 Stitch definitions, stitches, and runs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict


class StitchNodeHttpResponse(BaseModel):
    """HTTP response DTO representing a static node in a Stitch WorkflowDefinition DAG."""

    node_key: str
    kind: str
    step_type: str
    parents: list[str] = Field(default_factory=list)
    edge_condition: str
    effect_policy: str
    wait_event_key: str | None = None
    queue_name: str


class StitchDefinitionHttpResponse(BaseModel):
    """HTTP response DTO representing a registered Stitch WorkflowDefinition DAG."""

    workflow_id: str
    version: int
    default_priority: str
    description: str
    nodes: list[StitchNodeHttpResponse] = Field(default_factory=list)


class RegisterStitchHttpRequest(BaseModel):
    """HTTP request DTO to register or update a Stitch for a tenant."""

    stitch_id: str | None = None
    workflow_id: str = Field(..., min_length=1)
    workflow_version: int = Field(default=1, ge=1)
    canonical_event_type: str = Field(..., min_length=1)
    is_trigger: bool = True
    condition_event_key: str | None = None
    idempotency_key_field: str = Field(default="id", min_length=1)
    concurrency_key_field: str | None = None
    resource_hint_field: str | None = None
    is_active: bool = True


class StitchHttpResponse(BaseModel):
    """HTTP response DTO representing a Stitch."""

    id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    canonical_event_type: str
    is_trigger: bool
    condition_event_key: str | None = None
    idempotency_key_field: str
    concurrency_key_field: str | None = None
    resource_hint_field: str | None = None
    is_active: bool


class TriggerStitchEventHttpRequest(BaseModel):
    """HTTP request DTO to dispatch a canonical event to matching Stitches on the tenant shard."""

    canonical_event_type: str = Field(..., min_length=1)
    payload: JsonDict
    event_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None


class TriggerStitchEventHttpResponse(BaseModel):
    """HTTP response DTO returned after dispatching a canonical event to Stitches."""

    started_run_ids: list[str] = Field(default_factory=list)
    deduplicated_run_ids: list[str] = Field(default_factory=list)
    signalled_step_ids: list[str] = Field(default_factory=list)


class StitchStepRunHttpResponse(BaseModel):
    """HTTP response DTO representing a StepRun inside a Stitch WorkflowRun."""

    step_run_id: str
    node_key: str
    status: str
    retry_count: int
    app_retry_count: int
    internal_retry_count: int
    iteration_count: int
    failure_code: str | None = None
    failure_detail: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class StitchRunHttpResponse(BaseModel):
    """HTTP response DTO representing a durable Stitch WorkflowRun and its steps."""

    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    status: str
    priority: str
    concurrency_key: str | None = None
    idempotency_key: str
    trace_id: str
    correlation_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[StitchStepRunHttpResponse] = Field(default_factory=list)


__all__ = [
    "RegisterStitchHttpRequest",
    "StitchDefinitionHttpResponse",
    "StitchHttpResponse",
    "StitchNodeHttpResponse",
    "StitchRunHttpResponse",
    "StitchStepRunHttpResponse",
    "TriggerStitchEventHttpRequest",
    "TriggerStitchEventHttpResponse",
]
