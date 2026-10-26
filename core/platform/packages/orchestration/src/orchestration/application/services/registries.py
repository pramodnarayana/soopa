"""In-memory registries for WorkflowDefinition, StepHandlerPort, and MatchPredicateEvaluatorPort."""

from __future__ import annotations

from collections.abc import Callable

from seedwork.domain.types import JsonDict

from orchestration.domain.constants import WorkflowErrorCode
from orchestration.domain.definition import WorkflowDefinition
from orchestration.domain.exceptions import (
    DagValidationError,
    Result,
    VersionUnavailableError,
    WorkflowError,
)
from orchestration.domain.matching import MatchPredicateEvaluatorPort
from orchestration.ports.inbound.step_handler_port import (
    StepHandlerPort,
    StepHandlerRegistryPort,
    WorkflowDefinitionRegistryPort,
)

type PredicateFn = Callable[[JsonDict], bool]


class InMemoryWorkflowDefinitionRegistry(WorkflowDefinitionRegistryPort):
    """Thread-safe in-memory registry of validated `(workflow_id, version)` definitions."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], WorkflowDefinition] = {}

    def register(
        self, definition: WorkflowDefinition
    ) -> Result[WorkflowDefinition, DagValidationError]:
        validation = definition.validate()
        if validation.is_err:
            return validation
        self._definitions[(definition.workflow_id, definition.version)] = definition
        return Result.ok(definition)

    def get(
        self, workflow_id: str, version: int
    ) -> Result[WorkflowDefinition, VersionUnavailableError]:
        defn = self._definitions.get((workflow_id, version))
        if defn is None:
            return Result.err(VersionUnavailableError.for_version(workflow_id, version))
        return Result.ok(defn)


class InMemoryStepHandlerRegistry(StepHandlerRegistryPort):
    """In-memory registry mapping `step_type` to `StepHandlerPort` adapters."""

    def __init__(self) -> None:
        self._handlers: dict[str, StepHandlerPort[JsonDict, JsonDict]] = {}

    def register(self, handler: StepHandlerPort[JsonDict, JsonDict]) -> None:
        self._handlers[handler.step_type] = handler

    def get(self, step_type: str) -> Result[StepHandlerPort[JsonDict, JsonDict], WorkflowError]:
        handler = self._handlers.get(step_type)
        if handler is None:
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.STEP_HANDLER_NOT_FOUND,
                    message=f"No StepHandlerPort registered for step_type '{step_type}'.",
                    details={"step_type": step_type},
                )
            )
        return Result.ok(handler)


class InMemoryPredicateRegistry(MatchPredicateEvaluatorPort):
    """Pure predicate registry for BRANCH and WAIT_FOR_EVENT predicate evaluation."""

    def __init__(self) -> None:
        self._predicates: dict[str, PredicateFn] = {}

    def register(self, predicate_id: str, fn: PredicateFn) -> None:
        self._predicates[predicate_id] = fn

    def evaluate(self, predicate_id: str, payload: JsonDict) -> bool:
        fn = self._predicates.get(predicate_id)
        if fn is None:
            return False
        return fn(payload)


__all__ = [
    "InMemoryPredicateRegistry",
    "InMemoryStepHandlerRegistry",
    "InMemoryWorkflowDefinitionRegistry",
    "PredicateFn",
]
