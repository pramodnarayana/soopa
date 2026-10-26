"""Domain enumerations and enterprise constants for the Durable Workflow Engine."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class RunStatus(StrEnum):
    """Lifecycle states of a WorkflowRun aggregate."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED_VERSION_UNAVAILABLE = "BLOCKED_VERSION_UNAVAILABLE"


class StepStatus(StrEnum):
    """Lifecycle states of a StepRun node inside a WorkflowRun."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class AttemptStatus(StrEnum):
    """Lifecycle states of a single StepAttempt."""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    EVICTED = "EVICTED"


class NodeKind(StrEnum):
    """Static DAG node types supported by the Workflow Engine."""

    TASK = "TASK"
    WAIT_FOR_EVENT = "WAIT_FOR_EVENT"
    SLEEP = "SLEEP"
    BRANCH = "BRANCH"
    CHILD_WORKFLOW = "CHILD_WORKFLOW"
    REPEAT_UNTIL = "REPEAT_UNTIL"


class EdgeCondition(StrEnum):
    """Dependency transition condition on a DAG edge from a parent node to a child node."""

    ON_SUCCESS = "ON_SUCCESS"
    ON_FAILURE = "ON_FAILURE"
    ON_TIMEOUT = "ON_TIMEOUT"
    ON_FAILURE_OR_TIMEOUT = "ON_FAILURE_OR_TIMEOUT"
    ON_SKIPPED = "ON_SKIPPED"


class ConcurrencyStrategy(StrEnum):
    """Hatchet v1 window-function concurrency strategies."""

    SERIAL = "SERIAL"
    COALESCE_LATEST = "COALESCE_LATEST"  # Hatchet CANCEL_QUEUED_EXCEPT_NEWEST
    CANCEL_QUEUED_EXCEPT_OLDEST = "CANCEL_QUEUED_EXCEPT_OLDEST"
    CANCEL_IN_PROGRESS = "CANCEL_IN_PROGRESS"
    CANCEL_NEWEST = "CANCEL_NEWEST"
    GROUP_ROUND_ROBIN = "GROUP_ROUND_ROBIN"


class EffectPolicy(StrEnum):
    """Side-effect guarantee policy declared by each StepHandlerPort."""

    PURE = "PURE"
    IDEMPOTENT_EFFECT = "IDEMPOTENT_EFFECT"
    RECONCILABLE_EFFECT = "RECONCILABLE_EFFECT"
    OPERATOR_GATED_EFFECT = "OPERATOR_GATED_EFFECT"


class Priority(IntEnum):
    """Priority lanes ordered from lowest to highest numeric priority (Hatchet 1..4)."""

    BULK = 1
    REALTIME = 2
    HIGH = 3
    INTERACTIVE = 4


class StepFailureCode(StrEnum):
    """Strongly-typed failure codes returned by StepHandlerPort."""

    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    UPSTREAM_4XX = "UPSTREAM_4XX"
    ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    UNHANDLED_EXCEPTION = "UNHANDLED_EXCEPTION"
    LEASE_EXPIRED = "LEASE_EXPIRED"


class MatchKind(StrEnum):
    """Hatchet v1 match record category."""

    DAG_DEPENDENCY = "DAG_DEPENDENCY"
    SIGNAL_WAIT = "SIGNAL_WAIT"


class ConditionKind(StrEnum):
    """Hatchet v1 unified match condition kinds."""

    PARENT_OVERRIDE = "PARENT_OVERRIDE"
    SLEEP = "SLEEP"
    CANONICAL_EVENT = "CANONICAL_EVENT"


class MatchAction(StrEnum):
    """Hatchet v1 match actions evaluated in strict precedence: SKIP > CANCEL > CREATE > QUEUE > CREATE_MATCH."""

    SKIP = "SKIP"
    CANCEL = "CANCEL"
    CREATE = "CREATE"
    QUEUE = "QUEUE"
    CREATE_MATCH = "CREATE_MATCH"


MATCH_ACTION_PRECEDENCE: tuple[MatchAction, ...] = (
    MatchAction.SKIP,
    MatchAction.CANCEL,
    MatchAction.CREATE,
    MatchAction.QUEUE,
    MatchAction.CREATE_MATCH,
)


class InternalStepEventKey(StrEnum):
    """Internal step lifecycle event keys matched by PARENT_OVERRIDE conditions."""

    COMPLETED = "step.completed"
    FAILED = "step.failed"
    TIMED_OUT = "step.timed_out"
    CANCELLED = "step.cancelled"
    SKIPPED = "step.skipped"


class PayloadType(StrEnum):
    """Payload categories persisted in the decoupled workflow_payloads store (Hatchet v1_payload)."""

    RUN_INPUT = "RUN_INPUT"
    RUN_OUTPUT = "RUN_OUTPUT"
    STEP_INPUT = "STEP_INPUT"
    STEP_OUTPUT = "STEP_OUTPUT"
    MATCH_EVENT_DATA = "MATCH_EVENT_DATA"


class PayloadLocation(StrEnum):
    """Storage location of a workflow payload."""

    INLINE = "INLINE"
    EXTERNAL = "EXTERNAL"
    REFERENCE = "REFERENCE"


class IdempotencyEvictionPolicy(StrEnum):
    """Hatchet v1 idempotency key eviction modes."""

    TTL = "TTL"
    ON_TERMINAL_STATUS = "ON_TERMINAL_STATUS"


class QueueItemKind(StrEnum):
    """Work item types stored in the hot workflow_queue_items table."""

    EXECUTE = "EXECUTE"
    WAIT_TIMEOUT = "WAIT_TIMEOUT"
    SLEEP_WAKE = "SLEEP_WAKE"


class JoinPolicy(StrEnum):
    """Join semantics for CHILD_WORKFLOW fan-out/fan-in steps."""

    ALL = "ALL"
    ANY = "ANY"
    ALL_SETTLED = "ALL_SETTLED"


class WorkflowErrorCode(StrEnum):
    """First-class error codes for the Workflow Engine."""

    DAG_VALIDATION_FAILED = "DAG_VALIDATION_FAILED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    FENCING_TOKEN_MISMATCH = "FENCING_TOKEN_MISMATCH"  # noqa: S105 - Enum constant name contains TOKEN, not a secret
    VERSION_UNAVAILABLE = "VERSION_UNAVAILABLE"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    STEP_NOT_FOUND = "STEP_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    STEP_HANDLER_NOT_FOUND = "STEP_HANDLER_NOT_FOUND"
    CODEC_ERROR = "CODEC_ERROR"
    CONCURRENCY_REJECTED = "CONCURRENCY_REJECTED"


class ErrorDecisionKind(StrEnum):
    """Decision returned by StepErrorPolicyPort when a step fails."""

    RETRY = "RETRY"
    PARK_FOR_RATE_LIMIT = "PARK_FOR_RATE_LIMIT"
    FAIL_TERMINAL = "FAIL_TERMINAL"
    FAIL_AMBIGUOUS_OPERATOR_GATE = "FAIL_AMBIGUOUS_OPERATOR_GATE"


class TimerEventPrefix(StrEnum):
    """Strongly-typed internal event key prefixes for SLEEP and WAIT_FOR_EVENT timers."""

    SLEEP = "sleep"
    WAIT_TIMEOUT = "wait_timeout"

    def format_key(self, step_run_id: str) -> str:
        """Return the deterministic CNF condition event key for `step_run_id`."""
        return f"{self.value}.{step_run_id}"


__all__ = [
    "MATCH_ACTION_PRECEDENCE",
    "AttemptStatus",
    "ConcurrencyStrategy",
    "ConditionKind",
    "EdgeCondition",
    "EffectPolicy",
    "ErrorDecisionKind",
    "IdempotencyEvictionPolicy",
    "InternalStepEventKey",
    "JoinPolicy",
    "MatchAction",
    "MatchKind",
    "NodeKind",
    "PayloadLocation",
    "PayloadType",
    "Priority",
    "QueueItemKind",
    "RunStatus",
    "StepFailureCode",
    "StepStatus",
    "TimerEventPrefix",
    "WorkflowErrorCode",
]
