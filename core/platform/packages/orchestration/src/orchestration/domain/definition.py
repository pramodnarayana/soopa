"""Static DAG WorkflowDefinition, NodeDefinition, and policy value objects with pure validation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta

from orchestration.domain.constants import (
    ConcurrencyStrategy,
    EdgeCondition,
    EffectPolicy,
    JoinPolicy,
    NodeKind,
    Priority,
    StepFailureCode,
)
from orchestration.domain.exceptions import DagValidationError, Result


@dataclass(frozen=True)
class RetryPolicy:
    """Retry and exponential backoff policy for a workflow step."""

    max_attempts: int = 3
    max_internal_retries: int = 5
    initial_backoff: timedelta = timedelta(seconds=1)
    backoff_multiplier: float = 2.0
    max_backoff: timedelta = timedelta(minutes=5)
    non_retryable_codes: tuple[StepFailureCode, ...] = (
        StepFailureCode.VALIDATION_REJECTED,
        StepFailureCode.UPSTREAM_4XX,
        StepFailureCode.ENTITY_NOT_FOUND,
        StepFailureCode.AMBIGUOUS_EFFECT,
    )

    def compute_backoff(self, app_retry_count: int) -> timedelta:
        """Compute deterministic exponential backoff duration bounded by max_backoff."""
        exponent = max(0, app_retry_count - 1)
        raw_seconds = self.initial_backoff.total_seconds() * (self.backoff_multiplier**exponent)
        capped_seconds = min(raw_seconds, self.max_backoff.total_seconds())
        return timedelta(seconds=capped_seconds)


@dataclass(frozen=True)
class ConcurrencyPolicy:
    """Hatchet v1 concurrency strategy specification."""

    strategy_id: str
    strategy: ConcurrencyStrategy = ConcurrencyStrategy.GROUP_ROUND_ROBIN
    max_runs: int = 1
    key_template: str = "default"


@dataclass(frozen=True)
class RateLimitPolicy:
    """Token-bucket rate limit configuration keyed per resource/connection."""

    rate_limit_key: str
    units: int = 1
    capacity: int = 60
    refill_per_second: float = 1.0


@dataclass(frozen=True)
class WaitEventSpec:
    """Specification for a WAIT_FOR_EVENT node."""

    event_key: str
    resource_hint_template: str | None = None
    predicate_id: str | None = None
    timeout: timedelta = timedelta(hours=1)


@dataclass(frozen=True)
class RepeatUntilSpec:
    """Bounded loop specification for a REPEAT_UNTIL node."""

    predicate_id: str
    interval: timedelta
    max_iterations: int = 10


@dataclass(frozen=True)
class NodeDefinition:
    """Single node in a static WorkflowDefinition DAG."""

    node_key: str
    kind: NodeKind = NodeKind.TASK
    step_type: str = ""
    parents: tuple[str, ...] = ()
    edge_condition: EdgeCondition = EdgeCondition.ON_SUCCESS
    effect_policy: EffectPolicy = EffectPolicy.PURE
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    concurrency_policies: tuple[ConcurrencyPolicy, ...] = ()
    rate_limit_policy: RateLimitPolicy | None = None
    sleep_duration: timedelta | None = None
    wait_event: WaitEventSpec | None = None
    branch_predicate_id: str | None = None
    child_workflow_id: str | None = None
    join_policy: JoinPolicy = JoinPolicy.ALL
    repeat_until: RepeatUntilSpec | None = None
    step_timeout: timedelta = timedelta(minutes=5)
    queue_name: str = "default"


@dataclass(frozen=True)
class WorkflowDefinition:
    """Immutable, statically validated DAG workflow definition."""

    workflow_id: str
    version: int
    nodes: tuple[NodeDefinition, ...]
    default_priority: Priority = Priority.REALTIME
    workflow_concurrency: ConcurrencyPolicy | None = None
    description: str = ""

    def get_node(self, node_key: str) -> NodeDefinition | None:
        for node in self.nodes:
            if node.node_key == node_key:
                return node
        return None

    def root_nodes(self) -> tuple[NodeDefinition, ...]:
        return tuple(n for n in self.nodes if not n.parents)

    def children_of(self, parent_key: str) -> tuple[NodeDefinition, ...]:
        return tuple(n for n in self.nodes if parent_key in n.parents)

    def validate(self) -> Result[WorkflowDefinition, DagValidationError]:
        """Validate DAG structural integrity, acyclicity, and node kind invariants."""
        header_err = self._validate_header()
        if header_err is not None:
            return Result.err(header_err)

        node_map_res = self._build_unique_node_map()
        if node_map_res.is_err:
            return Result.err(node_map_res.unwrap_err())
        node_map = node_map_res.unwrap()

        if not self.root_nodes():
            return Result.err(
                DagValidationError.with_reason(
                    self.workflow_id,
                    "Workflow has no root entry nodes (every node has parents, indicating a cycle).",
                )
            )

        graph_res = self._build_and_validate_edges(node_map)
        if graph_res.is_err:
            return Result.err(graph_res.unwrap_err())
        in_degree, adjacency = graph_res.unwrap()

        if self._has_cycle(in_degree, adjacency):
            return Result.err(
                DagValidationError.with_reason(
                    self.workflow_id, "Workflow graph contains a cycle."
                )
            )

        return Result.ok(self)

    def _validate_header(self) -> DagValidationError | None:
        if not self.workflow_id.strip():
            return DagValidationError.with_reason(
                self.workflow_id, "workflow_id cannot be empty."
            )
        if self.version < 1:
            return DagValidationError.with_reason(
                self.workflow_id, "version must be >= 1."
            )
        if not self.nodes:
            return DagValidationError.with_reason(
                self.workflow_id, "Workflow must contain at least one node."
            )
        return None

    def _build_unique_node_map(
        self,
    ) -> Result[dict[str, NodeDefinition], DagValidationError]:
        node_map: dict[str, NodeDefinition] = {}
        for node in self.nodes:
            if not node.node_key.strip():
                return Result.err(
                    DagValidationError.with_reason(
                        self.workflow_id, "Node key cannot be empty."
                    )
                )
            if node.node_key in node_map:
                return Result.err(
                    DagValidationError.with_reason(
                        self.workflow_id, f"Duplicate node_key '{node.node_key}'."
                    )
                )
            node_map[node.node_key] = node
        return Result.ok(node_map)

    def _build_and_validate_edges(
        self, node_map: dict[str, NodeDefinition]
    ) -> Result[tuple[dict[str, int], dict[str, list[str]]], DagValidationError]:
        in_degree: dict[str, int] = {n.node_key: 0 for n in self.nodes}
        adjacency: dict[str, list[str]] = {n.node_key: [] for n in self.nodes}

        for node in self.nodes:
            edge_err = self._validate_node_parents(
                node, node_map, in_degree, adjacency
            )
            if edge_err is not None:
                return Result.err(edge_err)
            node_err = self._validate_node_invariants(node)
            if node_err is not None:
                return Result.err(node_err)

        return Result.ok((in_degree, adjacency))

    def _validate_node_parents(
        self,
        node: NodeDefinition,
        node_map: dict[str, NodeDefinition],
        in_degree: dict[str, int],
        adjacency: dict[str, list[str]],
    ) -> DagValidationError | None:
        seen_parents: set[str] = set()
        for parent_key in node.parents:
            if parent_key == node.node_key:
                return DagValidationError.with_reason(
                    self.workflow_id,
                    f"Node '{node.node_key}' cannot depend on itself.",
                )
            if parent_key not in node_map:
                return DagValidationError.with_reason(
                    self.workflow_id,
                    f"Node '{node.node_key}' references unknown parent '{parent_key}'.",
                )
            if parent_key in seen_parents:
                return DagValidationError.with_reason(
                    self.workflow_id,
                    f"Node '{node.node_key}' has duplicate parent '{parent_key}'.",
                )
            seen_parents.add(parent_key)
            adjacency[parent_key].append(node.node_key)
            in_degree[node.node_key] += 1
        return None

    def _has_cycle(
        self, in_degree: dict[str, int], adjacency: dict[str, list[str]]
    ) -> bool:
        queue: deque[str] = deque(k for k, deg in in_degree.items() if deg == 0)
        visited_count = 0
        while queue:
            current = queue.popleft()
            visited_count += 1
            for child in adjacency[current]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        return visited_count != len(self.nodes)

    def _validate_node_invariants(self, node: NodeDefinition) -> DagValidationError | None:
        if node.kind == NodeKind.TASK and not node.step_type.strip():
            return DagValidationError.with_reason(
                self.workflow_id,
                f"TASK node '{node.node_key}' must declare a non-empty step_type.",
            )
        if node.kind == NodeKind.SLEEP and (
            node.sleep_duration is None or node.sleep_duration.total_seconds() <= 0
        ):
            return DagValidationError.with_reason(
                self.workflow_id,
                f"SLEEP node '{node.node_key}' must declare a positive sleep_duration.",
            )
        if node.kind == NodeKind.WAIT_FOR_EVENT and (
            node.wait_event is None or not node.wait_event.event_key.strip()
        ):
            return DagValidationError.with_reason(
                self.workflow_id,
                f"WAIT_FOR_EVENT node '{node.node_key}' must declare a valid WaitEventSpec.",
            )
        if node.kind == NodeKind.BRANCH and (
            node.branch_predicate_id is None or not node.branch_predicate_id.strip()
        ):
            return DagValidationError.with_reason(
                self.workflow_id,
                f"BRANCH node '{node.node_key}' must declare a branch_predicate_id.",
            )
        if node.kind == NodeKind.CHILD_WORKFLOW and (
            node.child_workflow_id is None or not node.child_workflow_id.strip()
        ):
            return DagValidationError.with_reason(
                self.workflow_id,
                f"CHILD_WORKFLOW node '{node.node_key}' must declare a child_workflow_id.",
            )
        if node.kind == NodeKind.REPEAT_UNTIL and (
            node.repeat_until is None or node.repeat_until.max_iterations < 1
        ):
            return DagValidationError.with_reason(
                self.workflow_id,
                f"REPEAT_UNTIL node '{node.node_key}' must declare RepeatUntilSpec with max_iterations >= 1.",
            )
        return None


__all__ = [
    "ConcurrencyPolicy",
    "NodeDefinition",
    "RateLimitPolicy",
    "RepeatUntilSpec",
    "RetryPolicy",
    "WaitEventSpec",
    "WorkflowDefinition",
]
