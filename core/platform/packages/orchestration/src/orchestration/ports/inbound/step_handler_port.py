"""Inbound protocols for step handlers, reconciliation, codecs, and definition registries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar, runtime_checkable

from seedwork.domain.types import JsonDict

from orchestration.domain.constants import EffectPolicy
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.exceptions import (
    DagValidationError,
    Result,
    VersionUnavailableError,
    WorkflowError,
)
from orchestration.domain.failures import ErrorPolicyDecision, ReconcileOutcome, StepFailure
from orchestration.domain.run import StepRun

T = TypeVar("T")
TInput_contra = TypeVar("TInput_contra", contravariant=True)
TOutput_co = TypeVar("TOutput_co", covariant=True)


@dataclass(frozen=True, kw_only=True)
class StepContext:
    """Immutable execution context injected into a StepHandlerPort during step execution."""

    tenant_id: str
    run_id: str
    step_run_id: str
    node_key: str
    retry_count: int
    app_retry_count: int
    internal_retry_count: int
    idempotency_key: str
    trace_id: str
    correlation_id: str | None
    deadline: datetime


class CodecPort(Protocol[T]):
    """Typed boundary codec translating between domain value objects and JSON payloads."""

    def encode(self, value: T) -> Result[JsonDict, WorkflowError]: ...

    def decode(self, data: JsonDict) -> Result[T, WorkflowError]: ...


class StepHandlerPort(Protocol[TInput_contra, TOutput_co]):
    """Port implemented by step handlers in bounded contexts (e.g., IP Stitch steps).

    Must return `Result[TOutput_co, StepFailure]` and NEVER raise exceptions for known operational errors.
    """

    @property
    def step_type(self) -> str: ...

    @property
    def effect_policy(self) -> EffectPolicy: ...

    async def execute(
        self, context: StepContext, step_input: TInput_contra
    ) -> Result[TOutput_co, StepFailure]: ...


@runtime_checkable
class ReconcilableStepHandlerPort(StepHandlerPort[TInput_contra, TOutput_co], Protocol):
    """Port for RECONCILABLE_EFFECT step handlers that can query external state after a crash/lease expiry."""

    async def reconcile(
        self, context: StepContext, step_input: TInput_contra
    ) -> Result[ReconcileOutcome[TOutput_co], StepFailure]: ...


class StepHandlerRegistryPort(Protocol):
    """Registry mapping `step_type` identifiers to `StepHandlerPort` implementations."""

    def register(self, handler: StepHandlerPort[JsonDict, JsonDict]) -> None: ...

    def get(self, step_type: str) -> Result[StepHandlerPort[JsonDict, JsonDict], WorkflowError]: ...


class WorkflowDefinitionRegistryPort(Protocol):
    """Registry storing immutable, validated `(workflow_id, version)` DAG definitions."""

    def register(
        self, definition: WorkflowDefinition
    ) -> Result[WorkflowDefinition, DagValidationError]: ...

    def get(
        self, workflow_id: str, version: int
    ) -> Result[WorkflowDefinition, VersionUnavailableError]: ...


class StepErrorPolicyPort(Protocol):
    """Strategy port deciding how the Workflow Engine handles a StepFailure."""

    def decide(
        self,
        *,
        failure: StepFailure,
        step_run: StepRun,
        node_definition: NodeDefinition,
    ) -> ErrorPolicyDecision: ...


__all__ = [
    "CodecPort",
    "ReconcilableStepHandlerPort",
    "StepContext",
    "StepErrorPolicyPort",
    "StepHandlerPort",
    "StepHandlerRegistryPort",
    "WorkflowDefinitionRegistryPort",
]
