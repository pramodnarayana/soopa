"""First-class domain and operational error value objects for the Durable Workflow Engine.

Strictly adheres to the First-Class Error Handling standard:
- Known domain and operational outcomes are represented as immutable dataclasses (`WorkflowError`)
  and returned via `seedwork.domain.exceptions.Result[T, WorkflowError]`.
- Exceptions are NEVER raised for known domain or operational outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict

from orchestration.domain.constants import WorkflowErrorCode


@dataclass(frozen=True, kw_only=True)
class WorkflowError:
    """Base immutable value object for all known Workflow Engine errors."""

    code: WorkflowErrorCode
    message: str
    details: JsonDict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class DagValidationError(WorkflowError):
    """Returned when a WorkflowDefinition violates static DAG invariants."""

    code: WorkflowErrorCode = WorkflowErrorCode.DAG_VALIDATION_FAILED

    @classmethod
    def with_reason(cls, workflow_id: str, reason: str) -> DagValidationError:
        return cls(
            message=f"Workflow '{workflow_id}' failed DAG validation: {reason}",
            details={"workflow_id": workflow_id, "reason": reason},
        )


@dataclass(frozen=True, kw_only=True)
class InvalidTransitionError(WorkflowError):
    """Returned when an invalid state machine transition is attempted on a Run or StepRun."""

    code: WorkflowErrorCode = WorkflowErrorCode.INVALID_STATE_TRANSITION

    @classmethod
    def for_entity(
        cls,
        *,
        entity_type: str,
        entity_id: str,
        current_status: str,
        attempted_action: str,
    ) -> InvalidTransitionError:
        return cls(
            message=(
                f"Cannot perform '{attempted_action}' on {entity_type} '{entity_id}' "
                f"while in status '{current_status}'."
            ),
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "current_status": current_status,
                "attempted_action": attempted_action,
            },
        )


@dataclass(frozen=True, kw_only=True)
class FencingTokenMismatchError(WorkflowError):
    """Returned when a stale/zombie worker attempts to complete or fail a step with an outdated retry_count."""

    code: WorkflowErrorCode = WorkflowErrorCode.FENCING_TOKEN_MISMATCH

    @classmethod
    def for_step(
        cls,
        *,
        step_run_id: str,
        expected_retry_count: int,
        actual_retry_count: int,
    ) -> FencingTokenMismatchError:
        return cls(
            message=(
                f"Fencing token mismatch on step '{step_run_id}': "
                f"expected retry_count={expected_retry_count}, got {actual_retry_count}."
            ),
            details={
                "step_run_id": step_run_id,
                "expected_retry_count": expected_retry_count,
                "actual_retry_count": actual_retry_count,
            },
        )


@dataclass(frozen=True, kw_only=True)
class VersionUnavailableError(WorkflowError):
    """Returned when a run references an unregistered (workflow_id, workflow_version)."""

    code: WorkflowErrorCode = WorkflowErrorCode.VERSION_UNAVAILABLE

    @classmethod
    def for_version(cls, workflow_id: str, version: int) -> VersionUnavailableError:
        return cls(
            message=f"Workflow '{workflow_id}' version {version} is not registered.",
            details={"workflow_id": workflow_id, "workflow_version": version},
        )


@dataclass(frozen=True, kw_only=True)
class DuplicateIdempotencyKeyError(WorkflowError):
    """Returned when an idempotency key is already actively claimed by another run."""

    code: WorkflowErrorCode = WorkflowErrorCode.DUPLICATE_IDEMPOTENCY_KEY
    existing_run_id: str = ""

    @classmethod
    def for_key(
        cls, *, workflow_id: str, idempotency_key: str, existing_run_id: str
    ) -> DuplicateIdempotencyKeyError:
        return cls(
            message=(
                f"Idempotency key '{idempotency_key}' for workflow '{workflow_id}' "
                f"is already claimed by run '{existing_run_id}'."
            ),
            existing_run_id=existing_run_id,
            details={
                "workflow_id": workflow_id,
                "idempotency_key": idempotency_key,
                "existing_run_id": existing_run_id,
            },
        )


@dataclass(frozen=True, kw_only=True)
class RunNotFoundError(WorkflowError):
    """Returned when a WorkflowRun cannot be found."""

    code: WorkflowErrorCode = WorkflowErrorCode.RUN_NOT_FOUND

    @classmethod
    def for_id(cls, run_id: str) -> RunNotFoundError:
        return cls(
            message=f"Workflow run '{run_id}' not found.",
            details={"run_id": run_id},
        )


@dataclass(frozen=True, kw_only=True)
class StepNotFoundError(WorkflowError):
    """Returned when a StepRun node cannot be found on a WorkflowRun."""

    code: WorkflowErrorCode = WorkflowErrorCode.STEP_NOT_FOUND

    @classmethod
    def for_node(cls, run_id: str, node_key: str) -> StepNotFoundError:
        return cls(
            message=f"Step node '{node_key}' not found in workflow run '{run_id}'.",
            details={"run_id": run_id, "node_key": node_key},
        )


@dataclass(frozen=True, kw_only=True)
class ConcurrencyRejectedError(WorkflowError):
    """Returned when CANCEL_NEWEST rejects a newly triggered run because the key is at capacity."""

    code: WorkflowErrorCode = WorkflowErrorCode.CONCURRENCY_REJECTED

    @classmethod
    def for_key(cls, concurrency_key: str) -> ConcurrencyRejectedError:
        return cls(
            message=f"Run rejected by CANCEL_NEWEST policy for concurrency key '{concurrency_key}'.",
            details={"concurrency_key": concurrency_key},
        )


__all__ = [
    "ConcurrencyRejectedError",
    "DagValidationError",
    "DuplicateIdempotencyKeyError",
    "FencingTokenMismatchError",
    "InvalidTransitionError",
    "Result",
    "RunNotFoundError",
    "StepNotFoundError",
    "VersionUnavailableError",
    "WorkflowError",
]
