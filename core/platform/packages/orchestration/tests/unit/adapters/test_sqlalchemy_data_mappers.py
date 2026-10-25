"""Unit tests for all explicit static Data Mappers on SqlAlchemyWorkflow* repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from orchestration.adapters.outbound.database.models import (
    WorkflowPausedQueueItemModel,
    WorkflowQueueItemModel,
)
from orchestration.adapters.outbound.database.repositories import (
    SqlAlchemyWorkflowConcurrencyRepository,
    SqlAlchemyWorkflowIdempotencyRepository,
    SqlAlchemyWorkflowMatchRepository,
    SqlAlchemyWorkflowPayloadStoreRepository,
    SqlAlchemyWorkflowQueueRepository,
    SqlAlchemyWorkflowRateLimitRepository,
    SqlAlchemyWorkflowRunRepository,
)
from orchestration.domain.constants import (
    AttemptStatus,
    ConditionKind,
    IdempotencyEvictionPolicy,
    MatchAction,
    MatchKind,
    NodeKind,
    PayloadType,
    Priority,
    QueueItemKind,
    RunStatus,
    StepStatus,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.matching import MatchCondition, WorkflowMatch
from orchestration.domain.run import (
    ActiveLease,
    IdempotencyKeyRecord,
    PayloadRecord,
    StepAttempt,
    WorkflowRun,
)
from orchestration.domain.scheduling import ConcurrencySlot, RateLimitBucket


def test_workflow_run_and_step_and_attempt_and_lease_data_mappers_roundtrip() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    defn = WorkflowDefinition(
        workflow_id="energy.flow",
        version=1,
        nodes=(NodeDefinition(node_key="s1", kind=NodeKind.TASK, step_type="t.1"),),
    )
    run = WorkflowRun.create(
        tenant_id="ten_1",
        definition=defn,
        idempotency_key="idem_1",
        trace_id="trc_1",
        now=now,
    )

    orm_run = SqlAlchemyWorkflowRunRepository._to_orm_model(run)
    orm_step = SqlAlchemyWorkflowRunRepository._step_to_orm_model(run.steps["s1"])

    run.status = RunStatus.RUNNING
    run.steps["s1"].status = StepStatus.RUNNING
    run.steps["s1"].retry_count = 2
    SqlAlchemyWorkflowRunRepository._update_record_from_domain(orm_run, run)
    SqlAlchemyWorkflowRunRepository._update_step_record_from_domain(
        orm_step, run.steps["s1"]
    )

    restored = SqlAlchemyWorkflowRunRepository._to_domain_model(orm_run, (orm_step,))
    assert restored.id == run.id
    assert restored.status == RunStatus.RUNNING
    assert restored.steps["s1"].status == StepStatus.RUNNING
    assert restored.steps["s1"].retry_count == 2

    # StepAttempt mapper roundtrip
    attempt = StepAttempt(
        id="wf_att_1",
        step_run_id=run.steps["s1"].id,
        tenant_id="ten_1",
        retry_count=2,
        app_retry_count=1,
        internal_retry_count=1,
        worker_id="wrk_1",
        status=AttemptStatus.RUNNING,
        started_at=now,
    )
    orm_att = SqlAlchemyWorkflowRunRepository._attempt_to_orm_model(attempt)
    updated_att = replace(
        attempt,
        status=AttemptStatus.SUCCEEDED,
        is_app_error=False,
        outcome_code="OK",
        finished_at=now + timedelta(seconds=2),
    )
    SqlAlchemyWorkflowRunRepository._update_attempt_record_from_domain(
        orm_att, updated_att
    )
    restored_att = SqlAlchemyWorkflowRunRepository._attempt_to_domain_model(orm_att)
    assert restored_att.status == AttemptStatus.SUCCEEDED
    assert restored_att.outcome_code == "OK"

    # ActiveLease mapper roundtrip
    lease = ActiveLease(
        step_run_id=run.steps["s1"].id,
        step_created_at=now,
        retry_count=2,
        run_id=run.id,
        tenant_id="ten_1",
        worker_id="wrk_1",
        lease_expires_at=now + timedelta(seconds=30),
        timeout_at=now + timedelta(minutes=5),
    )
    orm_lease = SqlAlchemyWorkflowRunRepository._lease_to_orm_model(lease)
    restored_lease = SqlAlchemyWorkflowRunRepository._lease_to_domain_model(orm_lease)
    assert restored_lease == lease


def test_workflow_match_and_condition_data_mappers_roundtrip() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    cond = MatchCondition(
        id="wf_cnd_1",
        match_id="wf_mtc_1",
        tenant_id="ten_1",
        or_group_id="grp_1",
        condition_kind=ConditionKind.PARENT_OVERRIDE,
        event_key="step.completed",
        event_resource_hint="stp_1",
        predicate_id=None,
        readable_data_key="parent_a",
        action=MatchAction.QUEUE,
        created_at=now,
    )
    match = WorkflowMatch(
        id="wf_mtc_1",
        tenant_id="ten_1",
        run_id="wfr_1",
        step_run_id="stp_2",
        step_created_at=now,
        node_key="step_b",
        kind=MatchKind.DAG_DEPENDENCY,
        conditions=(cond,),
        existing_data={"seed": 1},
        created_at=now,
    )

    orm_match = SqlAlchemyWorkflowMatchRepository._to_orm_model(match)
    orm_cond = SqlAlchemyWorkflowMatchRepository._condition_to_orm_model(cond)

    satisfied_cond = replace(cond, is_satisfied=True, matched_data={"val": 42})
    satisfied_match = replace(
        match,
        conditions=(satisfied_cond,),
        is_satisfied=True,
        resolved_action=MatchAction.QUEUE,
    )
    SqlAlchemyWorkflowMatchRepository._update_record_from_domain(
        orm_match, satisfied_match
    )
    SqlAlchemyWorkflowMatchRepository._update_condition_record_from_domain(
        orm_cond, satisfied_cond
    )

    restored = SqlAlchemyWorkflowMatchRepository._to_domain_model(
        orm_match, (orm_cond,)
    )
    assert restored.is_satisfied
    assert restored.resolved_action == MatchAction.QUEUE
    assert restored.conditions[0].matched_data == {"val": 42}


def test_queue_concurrency_rate_limit_payload_and_idempotency_mappers() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    # 1. QueueItem & PausedQueueItem
    orm_q = WorkflowQueueItemModel(
        id=7,
        tenant_id="ten_1",
        run_id="wfr_1",
        step_run_id="stp_1",
        step_created_at=now,
        retry_count=0,
        item_kind=QueueItemKind.EXECUTE.value,
        queue_name="default",
        priority=int(Priority.HIGH),
        available_at=now,
        enqueued_at=now,
        concurrency_key="ck_1",
        rate_limit_key="rl_1",
        rate_limit_units=2,
    )
    dom_q = SqlAlchemyWorkflowQueueRepository._to_domain_model(orm_q)
    assert dom_q.priority == Priority.HIGH
    assert dom_q.rate_limit_units == 2

    orm_pq = WorkflowPausedQueueItemModel(
        id=9,
        tenant_id="ten_1",
        rate_limit_key="rl_1",
        run_id="wfr_1",
        step_run_id="stp_1",
        step_created_at=now,
        retry_count=0,
        queue_name="default",
        priority=int(Priority.REALTIME),
        requeue_after=now + timedelta(seconds=30),
        concurrency_key="ck_1",
        rate_limit_units=1,
        created_at=now,
    )
    dom_pq = SqlAlchemyWorkflowQueueRepository._paused_to_domain_model(orm_pq)
    assert dom_pq.id == 9

    # 2. ConcurrencySlot
    slot = ConcurrencySlot(
        sort_id=1,
        tenant_id="ten_1",
        strategy_id="strat_1",
        concurrency_key="ck_1",
        run_id="wfr_1",
        step_run_id="stp_1",
        step_created_at=now,
        retry_count=0,
        next_strategy_ids=("strat_2",),
        created_at=now,
    )
    orm_slot = SqlAlchemyWorkflowConcurrencyRepository._to_orm_model(slot)
    filled_slot = replace(slot, is_filled=True, acquired_at=now, next_strategy_ids=())
    SqlAlchemyWorkflowConcurrencyRepository._update_record_from_domain(
        orm_slot, filled_slot
    )
    restored_slot = SqlAlchemyWorkflowConcurrencyRepository._to_domain_model(orm_slot)
    assert restored_slot.is_filled
    assert restored_slot.next_strategy_ids == ()

    # 3. RateLimitBucket
    bucket = RateLimitBucket(
        tenant_id="ten_1",
        rate_limit_key="rl_1",
        capacity=60,
        refill_per_second=2.0,
        tokens=55.0,
        refilled_at=now,
    )
    orm_bucket = SqlAlchemyWorkflowRateLimitRepository._to_orm_model(bucket)
    paused_bucket = bucket.apply_upstream_pause(timedelta(seconds=15), now)
    SqlAlchemyWorkflowRateLimitRepository._update_record_from_domain(
        orm_bucket, paused_bucket
    )
    restored_bucket = SqlAlchemyWorkflowRateLimitRepository._to_domain_model(orm_bucket)
    assert restored_bucket.paused_until == now + timedelta(seconds=15)

    # 4. PayloadRecord
    payload = PayloadRecord.create_inline(
        tenant_id="ten_1",
        owner_id="wfr_1",
        owner_created_at=now,
        payload_type=PayloadType.RUN_INPUT,
        content={"k": "v"},
        size_bytes=12,
    )
    orm_payload = SqlAlchemyWorkflowPayloadStoreRepository._to_orm_model(payload)
    updated_payload = replace(payload, inline_content={"k": "v2"}, size_bytes=14)
    SqlAlchemyWorkflowPayloadStoreRepository._update_record_from_domain(
        orm_payload, updated_payload
    )
    restored_payload = SqlAlchemyWorkflowPayloadStoreRepository._to_domain_model(
        orm_payload
    )
    assert restored_payload.inline_content == {"k": "v2"}

    # 5. IdempotencyKeyRecord
    idem = IdempotencyKeyRecord(
        tenant_id="ten_1",
        workflow_id="wf_1",
        key="k_1",
        claimed_by_run_id="wfr_1",
        eviction_policy=IdempotencyEvictionPolicy.ON_TERMINAL_STATUS,
        expires_at=now + timedelta(hours=1),
        updated_at=now,
    )
    orm_idem = SqlAlchemyWorkflowIdempotencyRepository._to_orm_model(idem)
    updated_idem = replace(idem, claimed_by_run_id="wfr_2")
    SqlAlchemyWorkflowIdempotencyRepository._update_record_from_domain(
        orm_idem, updated_idem
    )
    restored_idem = SqlAlchemyWorkflowIdempotencyRepository._to_domain_model(orm_idem)
    assert restored_idem.claimed_by_run_id == "wfr_2"
