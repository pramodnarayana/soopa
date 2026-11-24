"""Pydantic HTTP request and response DTOs for Layer-4 Stitch definitions, stitches, and runs."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator
from seedwork.domain.types import JsonDict, JsonPrimitive


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
    boundary: str | None = None
    track: int = 0


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
    name: str = Field(default="", max_length=255)
    description: str = Field(default="")
    mapping_spec_id: str | None = None
    canonical_event_type: str = Field(..., min_length=1)
    target_workflow_id: str | None = None
    workflow_id: str | None = None
    workflow_version: int = 1
    is_trigger: bool = True
    idempotency_key_field: str = ""
    concurrency_key_field: str = ""
    filter_conditions: dict[str, JsonPrimitive] = Field(default_factory=dict)
    is_active: bool = True
    linked_stitch_id: str | None = None

    @model_validator(mode="after")
    def resolve_workflow_ids(self) -> Self:
        if not self.target_workflow_id and self.workflow_id:
            self.target_workflow_id = self.workflow_id
        elif not self.workflow_id and self.target_workflow_id:
            self.workflow_id = self.target_workflow_id
        if not self.target_workflow_id:
            raise ValueError("target_workflow_id or workflow_id is required.")
        return self


class StitchHttpResponse(BaseModel):
    """HTTP response DTO representing a Stitch."""

    id: str
    tenant_id: str
    canonical_event_type: str
    target_workflow_id: str = ""
    workflow_id: str = ""
    name: str = ""
    description: str = ""
    mapping_spec_id: str | None = None
    filter_conditions: dict[str, JsonPrimitive] = Field(default_factory=dict)
    is_active: bool
    linked_stitch_id: str | None = None

    @model_validator(mode="after")
    def sync_workflow_ids(self) -> Self:
        if not self.target_workflow_id and self.workflow_id:
            self.target_workflow_id = self.workflow_id
        elif not self.workflow_id and self.target_workflow_id:
            self.workflow_id = self.target_workflow_id
        return self


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


class UpdateStitchHttpRequest(BaseModel):
    """HTTP request DTO to update mutable properties of an existing Stitch."""

    name: str | None = None
    description: str | None = None
    mapping_spec_id: str | None = None
    filter_conditions: dict[str, JsonPrimitive] | None = None
    is_active: bool | None = None


class ToggleStitchStateHttpRequest(BaseModel):
    """HTTP request DTO to explicitly set the activation state of a Stitch."""

    is_active: bool


__all__ = [
    "RegisterStitchHttpRequest",
    "StitchDefinitionHttpResponse",
    "StitchHttpResponse",
    "StitchNodeHttpResponse",
    "StitchRunHttpResponse",
    "StitchStepRunHttpResponse",
    "ToggleStitchStateHttpRequest",
    "TriggerStitchEventHttpRequest",
    "TriggerStitchEventHttpResponse",
    "UpdateStitchHttpRequest",
]
