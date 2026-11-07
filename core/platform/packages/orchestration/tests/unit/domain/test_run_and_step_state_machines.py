"""Unit tests for WorkflowRun, StepRun 3-counter retries, fencing tokens, and zero-copy PayloadRecord."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orchestration.domain.constants import (
    NodeKind,
    PayloadLocation,
    PayloadType,
    RunStatus,
    StepFailureCode,
    StepStatus,
    WorkflowErrorCode,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.run import PayloadRecord, WorkflowRun


def _sample_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_id="energy.settlement",
        version=1,
        nodes=(
            NodeDefinition(node_key="step_a", kind=NodeKind.TASK, step_type="t.a"),
            NodeDefinition(
                node_key="step_b",
                kind=NodeKind.TASK,
                step_type="t.b",
                parents=("step_a",),
            ),
        ),
    )


def test_hatchet_three_counter_retry_and_fencing_token_protection() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    run = WorkflowRun.create(
        tenant_id="ten_1",
        definition=_sample_definition(),
        idempotency_key="idem_1",
        trace_id="trc_1",
        now=now,
    )
    assert run.status == RunStatus.QUEUED
    assert run.steps["step_a"].status == StepStatus.READY
    assert run.steps["step_b"].status == StepStatus.PENDING

    # 1. Worker 1 claims step_a (retry_count = 0)
    claim1 = run.claim_step(node_key="step_a", worker_id="wrk_1", now=now)
    assert claim1.is_ok
    attempt1, lease1 = claim1.unwrap()
    assert attempt1.retry_count == 0
    assert lease1.retry_count == 0
    assert run.status.value == RunStatus.RUNNING.value

    # 2. Rate-limit park does NOT increment retry_count, app_retry_count, or internal_retry_count
    park_res = run.schedule_step_retry(
        node_key="step_a",
        fencing_retry_count=0,
        failure_code=StepFailureCode.RATE_LIMITED,
        failure_detail="429 Too Many Requests",
        delay=timedelta(seconds=30),
        is_app_error=False,
        is_rate_limit_park=True,
    )
    assert park_res.is_ok
    step_a = park_res.unwrap()
    assert step_a.retry_count == 0
    assert step_a.app_retry_count == 0
    assert step_a.internal_retry_count == 0

    # 3. Re-ready and claim again, then simulate a worker crash (is_app_error=False)
    assert run.mark_step_ready("step_a").is_ok
    assert run.claim_step(node_key="step_a", worker_id="wrk_1", now=now).is_ok
    crash_res = run.schedule_step_retry(
        node_key="step_a",
        fencing_retry_count=0,
        failure_code=StepFailureCode.LEASE_EXPIRED,
        failure_detail="Worker OOM killed",
        delay=timedelta(seconds=1),
        is_app_error=False,
    )
    assert crash_res.is_ok
    step_a = crash_res.unwrap()
    assert step_a.retry_count == 1
    assert step_a.app_retry_count == 0  # User retry budget untouched!
    assert step_a.internal_retry_count == 1

    # 4. Zombie worker 1 tries to complete step_a with stale fencing_retry_count=0 -> rejected!
    assert run.mark_step_ready("step_a").is_ok
    assert run.claim_step(node_key="step_a", worker_id="wrk_2", now=now).is_ok
    zombie_res = run.complete_step(
        node_key="step_a",
        fencing_retry_count=0,
        now=now,
    )
    assert zombie_res.is_err
    assert zombie_res.unwrap_err().code == WorkflowErrorCode.FENCING_TOKEN_MISMATCH

    # 5. Application error increments both retry_count and app_retry_count
    app_err_res = run.schedule_step_retry(
        node_key="step_a",
        fencing_retry_count=1,
        failure_code=StepFailureCode.UPSTREAM_5XX,
        failure_detail="503 Service Unavailable",
        delay=timedelta(seconds=2),
        is_app_error=True,
    )
    assert app_err_res.is_ok
    step_a = app_err_res.unwrap()
    assert step_a.retry_count == 2
    assert step_a.app_retry_count == 1
    assert step_a.internal_retry_count == 1


def test_operator_replay_increments_fencing_token_and_resets_app_retry_count() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    run = WorkflowRun.create(
        tenant_id="ten_1",
        definition=_sample_definition(),
        idempotency_key="idem_2",
        trace_id="trc_2",
        now=now,
    )
    run.claim_step(node_key="step_a", worker_id="wrk_1", now=now)
    run.fail_step_terminally(
        node_key="step_a",
        fencing_retry_count=0,
        failure_code=StepFailureCode.UPSTREAM_5XX,
        failure_detail="Exhausted retries",
        now=now,
    )
    run.cancel_step(node_key="step_b", now=now)
    run.finalize_after_match_propagation(now=now)
    assert run.status == RunStatus.FAILED

    replay_res = run.replay_from_failed_step(node_key="step_a")
    assert replay_res.is_ok
    replayed = replay_res.unwrap()
    assert replayed.retry_count == 1
    assert replayed.app_retry_count == 0
    assert replayed.internal_retry_count == 0
    assert replayed.status == StepStatus.READY
    assert run.status.value == RunStatus.QUEUED.value


def test_zero_copy_payload_reference_record() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    ref = PayloadRecord.create_reference(
        tenant_id="ten_1",
        owner_id="stp_1",
        owner_created_at=now,
        payload_type=PayloadType.STEP_INPUT,
        reference_owner_id="wfr_1",
        reference_created_at=now,
    )
    assert ref.location == PayloadLocation.REFERENCE
    assert ref.payload_reference_id == "wfr_1"
    assert ref.inline_content is None
