"""Hatchet v1 Unified CNF Condition-Matching Engine (v1_match + v1_match_condition).

Unifies parent completions (PARENT_OVERRIDE), durable timers (SLEEP), and canonical/external
events (CANONICAL_EVENT) into one Conjunctive Normal Form (AND of OR-groups) state machine
with strict action resolution precedence: SKIP > CANCEL > CREATE > QUEUE > CREATE_MATCH.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol

from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from orchestration.domain.constants import (
    MATCH_ACTION_PRECEDENCE,
    ConditionKind,
    EdgeCondition,
    InternalStepEventKey,
    MatchAction,
    MatchKind,
    NodeKind,
    TimerEventPrefix,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition


class MatchPredicateEvaluatorPort(Protocol):
    """Pure predicate evaluator for branch and event match conditions."""

    def evaluate(self, predicate_id: str, payload: JsonDict) -> bool: ...


@dataclass(frozen=True)
class MatchEvent:
    """Incoming internal step event, sleep expiration, or external canonical event."""

    tenant_id: str
    condition_kind: ConditionKind
    event_key: str
    resource_hint: str | None = None
    payload: JsonDict = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class MatchCondition:
    """Single clause inside a CNF WorkflowMatch (Hatchet v1_match_condition)."""

    id: str
    match_id: str
    tenant_id: str
    or_group_id: str
    condition_kind: ConditionKind
    event_key: str
    event_resource_hint: str | None
    predicate_id: str | None
    readable_data_key: str
    action: MatchAction
    is_satisfied: bool = False
    matched_data: JsonDict | None = None
    timeout_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def matches_event(
        self,
        event: MatchEvent,
        predicate_evaluator: MatchPredicateEvaluatorPort | None = None,
    ) -> bool:
        """Return True if this unsatisfied condition is triggered by the given event."""
        if self.is_satisfied:
            return False
        if self.tenant_id != event.tenant_id:
            return False
        if self.condition_kind != event.condition_kind:
            return False
        if self.event_key != event.event_key:
            return False
        if (
            self.event_resource_hint is not None
            and self.event_resource_hint != event.resource_hint
        ):
            return False
        if self.predicate_id is not None:
            if predicate_evaluator is None:
                return False
            if not predicate_evaluator.evaluate(self.predicate_id, event.payload):
                return False
        return True


@dataclass(frozen=True)
class WorkflowMatch:
    """CNF condition match aggregate governing when and how a StepRun activates (Hatchet v1_match)."""

    id: str
    tenant_id: str
    run_id: str
    step_run_id: str
    step_created_at: datetime
    node_key: str
    kind: MatchKind
    conditions: tuple[MatchCondition, ...]
    existing_data: JsonDict = field(default_factory=dict)
    is_satisfied: bool = False
    resolved_action: MatchAction | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def evaluate_satisfied_action(self) -> MatchAction | None:
        """Evaluate CNF (all distinct or_group_ids for an action have >=1 satisfied condition)
        in strict Hatchet precedence order: SKIP > CANCEL > CREATE > QUEUE > CREATE_MATCH.
        """
        for candidate_action in MATCH_ACTION_PRECEDENCE:
            action_conditions = [
                c for c in self.conditions if c.action == candidate_action
            ]
            if not action_conditions:
                continue
            total_groups = {c.or_group_id for c in action_conditions}
            satisfied_groups = {
                c.or_group_id for c in action_conditions if c.is_satisfied
            }
            if total_groups and total_groups == satisfied_groups:
                return candidate_action
        return None

    def apply_event(
        self,
        event: MatchEvent,
        predicate_evaluator: MatchPredicateEvaluatorPort | None = None,
    ) -> WorkflowMatch:
        """Apply an incoming event to all matching conditions and evaluate CNF resolution."""
        if self.is_satisfied:
            return self

        updated_conditions: list[MatchCondition] = []
        any_changed = False
        for cond in self.conditions:
            if cond.matches_event(event, predicate_evaluator):
                updated_conditions.append(
                    replace(
                        cond,
                        is_satisfied=True,
                        matched_data=dict(event.payload),
                    )
                )
                any_changed = True
            else:
                updated_conditions.append(cond)

        if not any_changed:
            return self

        tentative = replace(self, conditions=tuple(updated_conditions))
        winner = tentative.evaluate_satisfied_action()
        if winner is None:
            return tentative

        return replace(
            tentative,
            is_satisfied=True,
            resolved_action=winner,
        )

    def aggregated_payload(self) -> JsonDict:
        """Aggregate `existing_data` with `matched_data` keyed by `readable_data_key` (Hatchet mc_aggregated_data)."""
        merged: JsonDict = dict(self.existing_data)
        parents_dict: JsonDict = {}
        existing_parents = merged.get("parents")
        if isinstance(existing_parents, dict):
            parents_dict.update(existing_parents)

        for cond in self.conditions:
            if cond.is_satisfied and cond.matched_data is not None:
                parents_dict[cond.readable_data_key] = dict(cond.matched_data)

        if parents_dict:
            merged["parents"] = parents_dict
        return merged

    def reset_for_replayed_parents(
        self, replayed_step_ids: set[str]
    ) -> WorkflowMatch:
        """Reset a CANCEL-resolved or parent-referencing match when an upstream step is replayed or operator-skipped."""
        has_reference = any(
            c.event_resource_hint in replayed_step_ids for c in self.conditions
        )
        if not has_reference and self.resolved_action != MatchAction.CANCEL:
            return self

        reset_conditions = tuple(
            replace(c, is_satisfied=False, matched_data=None)
            if (
                c.event_resource_hint in replayed_step_ids
                or c.action == MatchAction.CANCEL
            )
            else c
            for c in self.conditions
        )
        return replace(
            self,
            conditions=reset_conditions,
            is_satisfied=False,
            resolved_action=None,
        )


class DagMatchCompiler:
    """Compiles a WorkflowDefinition into Hatchet-style CNF WorkflowMatch records."""

    @staticmethod
    def compile_initial_matches(
        *,
        tenant_id: str,
        run_id: str,
        definition: WorkflowDefinition,
        step_ids_by_node_key: dict[str, tuple[str, datetime]],
        now: datetime | None = None,
    ) -> tuple[WorkflowMatch, ...]:
        """Build initial DAG_DEPENDENCY or SIGNAL_WAIT matches for all non-root or wait/sleep nodes."""
        timestamp = now or datetime.now(UTC)
        matches: list[WorkflowMatch] = []

        for node in definition.nodes:
            step_run_id, step_created_at = step_ids_by_node_key[node.node_key]
            has_parents = len(node.parents) > 0
            needs_signal_stage = node.kind in (NodeKind.SLEEP, NodeKind.WAIT_FOR_EVENT)

            if not has_parents and not needs_signal_stage:
                # Pure root TASK/BRANCH/CHILD_WORKFLOW nodes start READY immediately without a match
                continue

            if not has_parents and needs_signal_stage:
                # Root SLEEP or WAIT_FOR_EVENT node goes straight to stage-2 SIGNAL_WAIT match
                matches.append(
                    DagMatchCompiler.build_signal_wait_match(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        step_run_id=step_run_id,
                        step_created_at=step_created_at,
                        node=node,
                        existing_data={},
                        now=timestamp,
                    )
                )
                continue

            # Node has parents: create stage-1 DAG_DEPENDENCY match.
            # If the node ALSO has a SLEEP or WAIT_FOR_EVENT, parent satisfaction triggers CREATE_MATCH
            # (two-stage activation) so the sleep/wait timer only starts after parents complete!
            positive_action = (
                MatchAction.CREATE_MATCH if needs_signal_stage else MatchAction.QUEUE
            )
            matches.append(
                DagMatchCompiler._build_parent_dependency_match(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    step_run_id=step_run_id,
                    step_created_at=step_created_at,
                    node=node,
                    step_ids_by_node_key=step_ids_by_node_key,
                    positive_action=positive_action,
                    now=timestamp,
                )
            )

        return tuple(matches)

    @staticmethod
    def _build_parent_dependency_match(
        *,
        tenant_id: str,
        run_id: str,
        step_run_id: str,
        step_created_at: datetime,
        node: NodeDefinition,
        step_ids_by_node_key: dict[str, tuple[str, datetime]],
        positive_action: MatchAction,
        now: datetime,
    ) -> WorkflowMatch:
        match_id = generate_id(SystemIdPrefix.WORKFLOW_MATCH.value)
        conditions: list[MatchCondition] = []

        if node.edge_condition == EdgeCondition.ON_SUCCESS:
            # Standard DAG child (Hatchet getParentInDAGGroupMatch):
            # - Distinct or_group_id per parent for QUEUE/CREATE_MATCH on COMPLETED (AND across all parents)
            # - Shared cancel_group_id across all parents for CANCEL on FAILED/TIMED_OUT/CANCELLED (OR across parents)
            # - Distinct skip_group_id per parent for SKIP on SKIPPED (skips if ALL parents skipped)
            shared_cancel_group = generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value)
            for parent_key in node.parents:
                parent_step_id, _ = step_ids_by_node_key[parent_key]
                queue_group = generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value)
                skip_group = generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value)

                conditions.append(
                    MatchCondition(
                        id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                        match_id=match_id,
                        tenant_id=tenant_id,
                        or_group_id=queue_group,
                        condition_kind=ConditionKind.PARENT_OVERRIDE,
                        event_key=InternalStepEventKey.COMPLETED.value,
                        event_resource_hint=parent_step_id,
                        predicate_id=None,
                        readable_data_key=parent_key,
                        action=positive_action,
                        created_at=now,
                    )
                )
                conditions.append(
                    MatchCondition(
                        id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                        match_id=match_id,
                        tenant_id=tenant_id,
                        or_group_id=skip_group,
                        condition_kind=ConditionKind.PARENT_OVERRIDE,
                        event_key=InternalStepEventKey.SKIPPED.value,
                        event_resource_hint=parent_step_id,
                        predicate_id=None,
                        readable_data_key=parent_key,
                        action=MatchAction.SKIP,
                        created_at=now,
                    )
                )
                for fail_evt in (
                    InternalStepEventKey.FAILED,
                    InternalStepEventKey.TIMED_OUT,
                    InternalStepEventKey.CANCELLED,
                ):
                    conditions.append(
                        MatchCondition(
                            id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                            match_id=match_id,
                            tenant_id=tenant_id,
                            or_group_id=shared_cancel_group,
                            condition_kind=ConditionKind.PARENT_OVERRIDE,
                            event_key=fail_evt.value,
                            event_resource_hint=parent_step_id,
                            predicate_id=None,
                            readable_data_key=parent_key,
                            action=MatchAction.CANCEL,
                            created_at=now,
                        )
                    )
        else:
            # Compensation / failure / timeout handler node (Hatchet JobKindONFAILURE):
            # - Shared or_group_id across parents for QUEUE/CREATE_MATCH when ANY parent matches the failure/timeout event
            # - Distinct or_group_id per parent for SKIP when ALL parents succeed/skip without triggering the failure edge
            shared_trigger_group = generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value)
            trigger_events = DagMatchCompiler._trigger_events_for_edge(node.edge_condition)

            for parent_key in node.parents:
                parent_step_id, _ = step_ids_by_node_key[parent_key]
                skip_group = generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value)

                for trig_evt in trigger_events:
                    conditions.append(
                        MatchCondition(
                            id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                            match_id=match_id,
                            tenant_id=tenant_id,
                            or_group_id=shared_trigger_group,
                            condition_kind=ConditionKind.PARENT_OVERRIDE,
                            event_key=trig_evt.value,
                            event_resource_hint=parent_step_id,
                            predicate_id=None,
                            readable_data_key=parent_key,
                            action=positive_action,
                            created_at=now,
                        )
                    )
                for non_trig_evt in (
                    InternalStepEventKey.COMPLETED,
                    InternalStepEventKey.SKIPPED,
                ):
                    if non_trig_evt not in trigger_events:
                        conditions.append(
                            MatchCondition(
                                id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                                match_id=match_id,
                                tenant_id=tenant_id,
                                or_group_id=skip_group,
                                condition_kind=ConditionKind.PARENT_OVERRIDE,
                                event_key=non_trig_evt.value,
                                event_resource_hint=parent_step_id,
                                predicate_id=None,
                                readable_data_key=parent_key,
                                action=MatchAction.SKIP,
                                created_at=now,
                            )
                        )

        return WorkflowMatch(
            id=match_id,
            tenant_id=tenant_id,
            run_id=run_id,
            step_run_id=step_run_id,
            step_created_at=step_created_at,
            node_key=node.node_key,
            kind=MatchKind.DAG_DEPENDENCY,
            conditions=tuple(conditions),
            existing_data={},
            created_at=now,
        )

    @staticmethod
    def build_signal_wait_match(
        *,
        tenant_id: str,
        run_id: str,
        step_run_id: str,
        step_created_at: datetime,
        node: NodeDefinition,
        existing_data: JsonDict,
        now: datetime | None = None,
    ) -> WorkflowMatch:
        """Build stage-2 SIGNAL_WAIT match for a SLEEP or WAIT_FOR_EVENT node."""
        timestamp = now or datetime.now(UTC)
        match_id = generate_id(SystemIdPrefix.WORKFLOW_MATCH.value)
        conditions: list[MatchCondition] = []

        if node.kind == NodeKind.SLEEP:
            assert node.sleep_duration is not None
            wake_at = timestamp + node.sleep_duration
            conditions.append(
                MatchCondition(
                    id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                    match_id=match_id,
                    tenant_id=tenant_id,
                    or_group_id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                    condition_kind=ConditionKind.SLEEP,
                    event_key=TimerEventPrefix.SLEEP.format_key(step_run_id),
                    event_resource_hint=step_run_id,
                    predicate_id=None,
                    readable_data_key=node.node_key,
                    action=MatchAction.QUEUE,
                    timeout_at=wake_at,
                    created_at=timestamp,
                )
            )
        elif node.kind == NodeKind.WAIT_FOR_EVENT:
            assert node.wait_event is not None
            timeout_at = timestamp + node.wait_event.timeout
            conditions.append(
                MatchCondition(
                    id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                    match_id=match_id,
                    tenant_id=tenant_id,
                    or_group_id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                    condition_kind=ConditionKind.CANONICAL_EVENT,
                    event_key=node.wait_event.event_key,
                    event_resource_hint=node.wait_event.resource_hint_template,
                    predicate_id=node.wait_event.predicate_id,
                    readable_data_key=node.node_key,
                    action=MatchAction.QUEUE,
                    timeout_at=timeout_at,
                    created_at=timestamp,
                )
            )
            # Timeout condition with CANCEL action so timeout resolves via CNF if event doesn't arrive
            conditions.append(
                MatchCondition(
                    id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                    match_id=match_id,
                    tenant_id=tenant_id,
                    or_group_id=generate_id(SystemIdPrefix.WORKFLOW_CONDITION.value),
                    condition_kind=ConditionKind.SLEEP,
                    event_key=TimerEventPrefix.WAIT_TIMEOUT.format_key(step_run_id),
                    event_resource_hint=step_run_id,
                    predicate_id=None,
                    readable_data_key=node.node_key,
                    action=MatchAction.CANCEL,
                    timeout_at=timeout_at,
                    created_at=timestamp,
                )
            )

        return WorkflowMatch(
            id=match_id,
            tenant_id=tenant_id,
            run_id=run_id,
            step_run_id=step_run_id,
            step_created_at=step_created_at,
            node_key=node.node_key,
            kind=MatchKind.SIGNAL_WAIT,
            conditions=tuple(conditions),
            existing_data=dict(existing_data),
            created_at=timestamp,
        )

    @staticmethod
    def _trigger_events_for_edge(
        edge_condition: EdgeCondition,
    ) -> tuple[InternalStepEventKey, ...]:
        if edge_condition == EdgeCondition.ON_FAILURE:
            return (InternalStepEventKey.FAILED,)
        if edge_condition == EdgeCondition.ON_TIMEOUT:
            return (InternalStepEventKey.TIMED_OUT,)
        if edge_condition == EdgeCondition.ON_FAILURE_OR_TIMEOUT:
            return (InternalStepEventKey.FAILED, InternalStepEventKey.TIMED_OUT)
        if edge_condition == EdgeCondition.ON_SKIPPED:
            return (InternalStepEventKey.SKIPPED,)
        return (InternalStepEventKey.COMPLETED,)


__all__ = [
    "DagMatchCompiler",
    "MatchCondition",
    "MatchEvent",
    "MatchPredicateEvaluatorPort",
    "WorkflowMatch",
]
