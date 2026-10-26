"""Unit tests for the Hatchet v1 Unified CNF Condition-Matching Engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orchestration.domain.constants import (
    ConditionKind,
    EdgeCondition,
    InternalStepEventKey,
    MatchAction,
    MatchKind,
    NodeKind,
)
from orchestration.domain.definition import (
    NodeDefinition,
    WaitEventSpec,
    WorkflowDefinition,
)
from orchestration.domain.matching import (
    DagMatchCompiler,
    MatchEvent,
)


def test_multi_parent_on_success_requires_all_parents_to_queue_or_any_parent_to_cancel() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    defn = WorkflowDefinition(
        workflow_id="fan_in_flow",
        version=1,
        nodes=(
            NodeDefinition(node_key="p1", kind=NodeKind.TASK, step_type="t.p1"),
            NodeDefinition(node_key="p2", kind=NodeKind.TASK, step_type="t.p2"),
            NodeDefinition(
                node_key="join_step",
                kind=NodeKind.TASK,
                step_type="t.join",
                parents=("p1", "p2"),
                edge_condition=EdgeCondition.ON_SUCCESS,
            ),
        ),
    )
    step_ids = {
        "p1": ("stp_p1", now),
        "p2": ("stp_p2", now),
        "join_step": ("stp_join", now),
    }

    matches = DagMatchCompiler.compile_initial_matches(
        tenant_id="ten_1",
        run_id="wfr_1",
        definition=defn,
        step_ids_by_node_key=step_ids,
        now=now,
    )
    assert len(matches) == 1
    join_match = matches[0]
    assert join_match.node_key == "join_step"
    assert join_match.kind == MatchKind.DAG_DEPENDENCY

    # 1. Parent p1 completes -> join_match is NOT yet satisfied (waiting on p2)
    after_p1 = join_match.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.COMPLETED.value,
            resource_hint="stp_p1",
            payload={"from_p1": 10},
            occurred_at=now,
        )
    )
    assert not after_p1.is_satisfied
    assert after_p1.resolved_action is None

    # 2. If p2 completes -> join_match resolves to QUEUE and aggregates both parent outputs!
    after_p2_ok = after_p1.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.COMPLETED.value,
            resource_hint="stp_p2",
            payload={"from_p2": 20},
            occurred_at=now,
        )
    )
    assert after_p2_ok.is_satisfied
    assert after_p2_ok.resolved_action == MatchAction.QUEUE
    assert after_p2_ok.aggregated_payload() == {
        "parents": {
            "p1": {"from_p1": 10},
            "p2": {"from_p2": 20},
        }
    }

    # 3. Alternatively, if p1 fails -> shared cancel_group_id immediately resolves to CANCEL!
    after_p1_fail = join_match.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.FAILED.value,
            resource_hint="stp_p1",
            payload={"err": "boom"},
            occurred_at=now,
        )
    )
    assert after_p1_fail.is_satisfied
    assert after_p1_fail.resolved_action == MatchAction.CANCEL

    # 4. If p1 completes and p2 is skipped -> shared skip_group_id immediately resolves to SKIP!
    after_p2_skipped = after_p1.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.SKIPPED.value,
            resource_hint="stp_p2",
            occurred_at=now,
        )
    )
    assert after_p2_skipped.is_satisfied
    assert after_p2_skipped.resolved_action == MatchAction.SKIP


def test_on_failure_compensation_node_queues_on_any_parent_failure_and_skips_when_all_succeed() -> (
    None
):
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    defn = WorkflowDefinition(
        workflow_id="comp_flow",
        version=1,
        nodes=(
            NodeDefinition(node_key="p1", kind=NodeKind.TASK, step_type="t.p1"),
            NodeDefinition(node_key="p2", kind=NodeKind.TASK, step_type="t.p2"),
            NodeDefinition(
                node_key="compensate",
                kind=NodeKind.TASK,
                step_type="t.comp",
                parents=("p1", "p2"),
                edge_condition=EdgeCondition.ON_FAILURE_OR_TIMEOUT,
            ),
        ),
    )
    step_ids = {
        "p1": ("stp_p1", now),
        "p2": ("stp_p2", now),
        "compensate": ("stp_comp", now),
    }

    comp_match = DagMatchCompiler.compile_initial_matches(
        tenant_id="ten_1",
        run_id="wfr_1",
        definition=defn,
        step_ids_by_node_key=step_ids,
        now=now,
    )[0]

    # When BOTH p1 and p2 succeed, compensate resolves to SKIP
    m1 = comp_match.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.COMPLETED.value,
            resource_hint="stp_p1",
        )
    )
    assert not m1.is_satisfied
    m2 = m1.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.COMPLETED.value,
            resource_hint="stp_p2",
        )
    )
    assert m2.is_satisfied
    assert m2.resolved_action == MatchAction.SKIP

    # When p1 times out, compensate immediately resolves to QUEUE
    m_timeout = comp_match.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.TIMED_OUT.value,
            resource_hint="stp_p1",
        )
    )
    assert m_timeout.is_satisfied
    assert m_timeout.resolved_action == MatchAction.QUEUE

    # When p2 is cancelled and p1 completed, compensate resolves to SKIP (all parents non-trigger)
    m_cancelled = m1.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.CANCELLED.value,
            resource_hint="stp_p2",
        )
    )
    assert m_cancelled.is_satisfied
    assert m_cancelled.resolved_action == MatchAction.SKIP


def test_two_stage_create_match_for_parent_dependent_wait_for_event_node() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    wait_node = NodeDefinition(
        node_key="wait_ack",
        kind=NodeKind.WAIT_FOR_EVENT,
        parents=("dispatch_cmd",),
        wait_event=WaitEventSpec(
            event_key="canonical.command_ack",
            resource_hint_template="meter_99",
            timeout=timedelta(minutes=15),
        ),
    )
    defn = WorkflowDefinition(
        workflow_id="two_stage_flow",
        version=1,
        nodes=(
            NodeDefinition(node_key="dispatch_cmd", kind=NodeKind.TASK, step_type="t.dispatch"),
            wait_node,
        ),
    )
    step_ids = {
        "dispatch_cmd": ("stp_dispatch", now),
        "wait_ack": ("stp_wait", now),
    }

    stage1_match = DagMatchCompiler.compile_initial_matches(
        tenant_id="ten_1",
        run_id="wfr_1",
        definition=defn,
        step_ids_by_node_key=step_ids,
        now=now,
    )[0]

    # Stage 1 has positive action CREATE_MATCH (not QUEUE)
    resolved_stage1 = stage1_match.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.PARENT_OVERRIDE,
            event_key=InternalStepEventKey.COMPLETED.value,
            resource_hint="stp_dispatch",
            payload={"cmd_id": "cmd_123"},
            occurred_at=now,
        )
    )
    assert resolved_stage1.is_satisfied
    assert resolved_stage1.resolved_action == MatchAction.CREATE_MATCH

    # Stage 2 SIGNAL_WAIT match is built only when parent completes at t + 5m
    stage2_time = now + timedelta(minutes=5)
    stage2_match = DagMatchCompiler.build_signal_wait_match(
        tenant_id="ten_1",
        run_id="wfr_1",
        step_run_id="stp_wait",
        step_created_at=now,
        node=wait_node,
        existing_data=resolved_stage1.aggregated_payload(),
        now=stage2_time,
    )
    assert stage2_match.kind == MatchKind.SIGNAL_WAIT

    # Canonical event arrives -> resolves to QUEUE and preserves parent data + event data
    resolved_stage2 = stage2_match.apply_event(
        MatchEvent(
            tenant_id="ten_1",
            condition_kind=ConditionKind.CANONICAL_EVENT,
            event_key="canonical.command_ack",
            resource_hint="meter_99",
            payload={"ack_status": "ACCEPTED"},
            occurred_at=stage2_time + timedelta(minutes=1),
        )
    )
    assert resolved_stage2.is_satisfied
    assert resolved_stage2.resolved_action == MatchAction.QUEUE
    assert resolved_stage2.aggregated_payload() == {
        "parents": {
            "dispatch_cmd": {"cmd_id": "cmd_123"},
            "wait_ack": {"ack_status": "ACCEPTED"},
        }
    }
