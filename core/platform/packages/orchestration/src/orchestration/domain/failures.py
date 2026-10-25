"""First-class step failure value objects and reconciliation outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Generic, TypeVar

from seedwork.domain.types import JsonDict

from orchestration.domain.constants import ErrorDecisionKind, StepFailureCode

T = TypeVar("T")
TOutput_co = TypeVar("TOutput_co", covariant=True)


@dataclass(frozen=True)
class RetryableFailure:
    """Transient step failure that may be retried or parked for rate-limit recovery."""

    code: StepFailureCode
    detail: str
    retry_after: timedelta | None = None
    is_app_error: bool = True
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalFailure:
    """Deterministic step failure that must not be retried and immediately triggers failure edges."""

    code: StepFailureCode
    detail: str
    metadata: JsonDict = field(default_factory=dict)


type StepFailure = RetryableFailure | TerminalFailure


@dataclass(frozen=True)
class ReconcileOutcome(Generic[TOutput_co]):  # noqa: UP046 - Covariant TypeVar required for ReconcilableStepHandlerPort Protocol return type
    """Outcome of querying an external system to check whether a prior attempt's effect already occurred."""

    found: bool
    adopted_output: TOutput_co | None = None

    @staticmethod
    def adopt(output: T) -> ReconcileOutcome[T]:
        return ReconcileOutcome(found=True, adopted_output=output)

    @staticmethod
    def not_found() -> ReconcileOutcome[None]:
        return ReconcileOutcome(found=False, adopted_output=None)


@dataclass(frozen=True)
class ErrorPolicyDecision:
    """Decision computed by StepErrorPolicyPort for a failed step attempt."""

    kind: ErrorDecisionKind
    delay: timedelta = timedelta(seconds=0)
    failure_code: StepFailureCode = StepFailureCode.UNHANDLED_EXCEPTION
    failure_detail: str = ""


__all__ = [
    "ErrorPolicyDecision",
    "ReconcileOutcome",
    "RetryableFailure",
    "StepFailure",
    "TerminalFailure",
]
