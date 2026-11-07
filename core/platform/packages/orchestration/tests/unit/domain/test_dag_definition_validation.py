"""Unit tests for static DAG WorkflowDefinition validation and RetryPolicy backoff."""

from __future__ import annotations

from datetime import timedelta

from orchestration.domain.constants import (
    EdgeCondition,
    NodeKind,
    WorkflowErrorCode,
)
from orchestration.domain.definition import (
    NodeDefinition,
    RepeatUntilSpec,
    RetryPolicy,
    WaitEventSpec,
    WorkflowDefinition,
)


def test_valid_diamond_and_compensation_dag_passes_validation() -> None:
    defn = WorkflowDefinition(
        workflow_id="energy.meter_stitch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="ingest",
                kind=NodeKind.TASK,
                step_type="stitch.ingest",
            ),
            NodeDefinition(
                node_key="enrich_weather",
                kind=NodeKind.TASK,
                step_type="stitch.weather",
                parents=("ingest",),
            ),
            NodeDefinition(
                node_key="enrich_tariff",
                kind=NodeKind.TASK,
                step_type="stitch.tariff",
                parents=("ingest",),
            ),
            NodeDefinition(
                node_key="settle",
                kind=NodeKind.TASK,
                step_type="stitch.settle",
                parents=("enrich_weather", "enrich_tariff"),
            ),
            NodeDefinition(
                node_key="compensate_failure",
                kind=NodeKind.TASK,
                step_type="stitch.compensate",
                parents=("settle",),
                edge_condition=EdgeCondition.ON_FAILURE_OR_TIMEOUT,
            ),
        ),
    )

    result = defn.validate()
    assert result.is_ok
    assert result.unwrap() == defn
    assert [n.node_key for n in defn.root_nodes()] == ["ingest"]
    assert [n.node_key for n in defn.children_of("ingest")] == [
        "enrich_weather",
        "enrich_tariff",
    ]


def test_dag_validation_rejects_cycles_and_invalid_structures() -> None:
    # 1. Cycle between A and B (with a root R so roots check passes)
    cyclic = WorkflowDefinition(
        workflow_id="cyclic_flow",
        version=1,
        nodes=(
            NodeDefinition(node_key="root", kind=NodeKind.TASK, step_type="t.root"),
            NodeDefinition(
                node_key="a",
                kind=NodeKind.TASK,
                step_type="t.a",
                parents=("root", "b"),
            ),
            NodeDefinition(
                node_key="b",
                kind=NodeKind.TASK,
                step_type="t.b",
                parents=("a",),
            ),
        ),
    )
    res_cycle = cyclic.validate()
    assert res_cycle.is_err
    assert res_cycle.unwrap_err().code == WorkflowErrorCode.DAG_VALIDATION_FAILED
    assert "cycle" in res_cycle.unwrap_err().message.lower()

    # 2. Unknown parent reference
    unknown_parent = WorkflowDefinition(
        workflow_id="bad_parent",
        version=1,
        nodes=(
            NodeDefinition(node_key="root", kind=NodeKind.TASK, step_type="t.root"),
            NodeDefinition(
                node_key="child",
                kind=NodeKind.TASK,
                step_type="t.child",
                parents=("missing_node",),
            ),
        ),
    )
    assert unknown_parent.validate().is_err

    # 3. Duplicate node key
    dup_node = WorkflowDefinition(
        workflow_id="dup_node",
        version=1,
        nodes=(
            NodeDefinition(node_key="step1", kind=NodeKind.TASK, step_type="t.1"),
            NodeDefinition(node_key="step1", kind=NodeKind.TASK, step_type="t.2"),
        ),
    )
    assert dup_node.validate().is_err


def test_node_kind_invariants_are_enforced() -> None:
    # SLEEP without positive sleep_duration fails
    bad_sleep = WorkflowDefinition(
        workflow_id="bad_sleep",
        version=1,
        nodes=(NodeDefinition(node_key="s1", kind=NodeKind.SLEEP, sleep_duration=None),),
    )
    assert bad_sleep.validate().is_err

    # WAIT_FOR_EVENT with valid WaitEventSpec passes
    good_wait = WorkflowDefinition(
        workflow_id="good_wait",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="w1",
                kind=NodeKind.WAIT_FOR_EVENT,
                wait_event=WaitEventSpec(
                    event_key="canonical.meter_read.normalized",
                    timeout=timedelta(minutes=30),
                ),
            ),
        ),
    )
    assert good_wait.validate().is_ok

    # REPEAT_UNTIL with valid spec passes
    good_repeat = WorkflowDefinition(
        workflow_id="good_repeat",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="r1",
                kind=NodeKind.REPEAT_UNTIL,
                step_type="stitch.poll_export_job",
                repeat_until=RepeatUntilSpec(
                    predicate_id="pred.job_done",
                    interval=timedelta(seconds=10),
                    max_iterations=5,
                ),
            ),
        ),
    )
    assert good_repeat.validate().is_ok


def test_retry_policy_exponential_backoff_caps_at_max_backoff() -> None:
    policy = RetryPolicy(
        max_attempts=5,
        initial_backoff=timedelta(seconds=2),
        backoff_multiplier=3.0,
        max_backoff=timedelta(seconds=15),
    )
    assert policy.compute_backoff(1) == timedelta(seconds=2)
    assert policy.compute_backoff(2) == timedelta(seconds=6)
    assert policy.compute_backoff(3) == timedelta(seconds=15)  # 18s capped to 15s
