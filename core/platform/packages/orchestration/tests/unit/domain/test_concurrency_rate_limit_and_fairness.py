"""Unit tests for Hatchet v1 Window-Function Concurrency, RateLimitBucket, and FairQueueSelector."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from orchestration.domain.constants import ConcurrencyStrategy, Priority, QueueItemKind
from orchestration.domain.scheduling import (
    ConcurrencySlot,
    ConcurrencyWindowEvaluator,
    FairQueueSelector,
    QueueItem,
    RateLimitBucket,
)


def _make_slot(
    sort_id: int,
    step_run_id: str,
    *,
    is_filled: bool = False,
    next_strategy_ids: tuple[str, ...] = (),
) -> ConcurrencySlot:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    return ConcurrencySlot(
        sort_id=sort_id,
        tenant_id="ten_1",
        strategy_id="strat_1",
        concurrency_key="meter_100",
        run_id=f"wfr_{sort_id}",
        step_run_id=step_run_id,
        step_created_at=now,
        retry_count=0,
        is_filled=is_filled,
        next_strategy_ids=next_strategy_ids,
        created_at=now,
    )


def test_concurrency_window_evaluator_all_strategies_and_multi_strategy_chaining() -> None:
    # 1. GROUP_ROUND_ROBIN / SERIAL: fills oldest waiting up to max_runs
    s1 = _make_slot(1, "stp_1", is_filled=True)
    s2 = _make_slot(2, "stp_2", is_filled=False)
    s3 = _make_slot(3, "stp_3", is_filled=False)
    res_serial = ConcurrencyWindowEvaluator.evaluate_key_group(
        strategy=ConcurrencyStrategy.SERIAL,
        max_runs=2,
        slots=(s1, s2, s3),
    )
    assert [s.step_run_id for s in res_serial.ready_to_enqueue] == ["stp_2"]
    assert [s.step_run_id for s in res_serial.remaining_waiting_slots] == ["stp_3"]
    assert len(res_serial.cancelled_slots) == 0

    # 2. CANCEL_IN_PROGRESS: newest wins and cancels older active + waiting slots!
    res_cancel_in_prog = ConcurrencyWindowEvaluator.evaluate_key_group(
        strategy=ConcurrencyStrategy.CANCEL_IN_PROGRESS,
        max_runs=1,
        slots=(s1, s2, s3),
    )
    assert [s.step_run_id for s in res_cancel_in_prog.ready_to_enqueue] == ["stp_3"]
    assert {s.step_run_id for s in res_cancel_in_prog.cancelled_slots} == {
        "stp_1",
        "stp_2",
    }

    # 3. CANCEL_NEWEST: oldest wins and cancels all newer slots
    res_cancel_newest = ConcurrencyWindowEvaluator.evaluate_key_group(
        strategy=ConcurrencyStrategy.CANCEL_NEWEST,
        max_runs=1,
        slots=(s1, s2, s3),
    )
    assert len(res_cancel_newest.ready_to_enqueue) == 0  # s1 is already filled
    assert {s.step_run_id for s in res_cancel_newest.cancelled_slots} == {
        "stp_2",
        "stp_3",
    }

    # 4. COALESCE_LATEST (CANCEL_QUEUED_EXCEPT_NEWEST): keeps active s1, keeps newest waiting s3, cancels s2
    res_coalesce = ConcurrencyWindowEvaluator.evaluate_key_group(
        strategy=ConcurrencyStrategy.COALESCE_LATEST,
        max_runs=1,
        slots=(s1, s2, s3),
    )
    assert [s.step_run_id for s in res_coalesce.remaining_waiting_slots] == ["stp_3"]
    assert [s.step_run_id for s in res_coalesce.cancelled_slots] == ["stp_2"]

    # 5. Multi-strategy chaining via next_strategy_ids
    chained = _make_slot(10, "stp_10", is_filled=False, next_strategy_ids=("strat_2",))
    res_chain = ConcurrencyWindowEvaluator.evaluate_key_group(
        strategy=ConcurrencyStrategy.GROUP_ROUND_ROBIN,
        max_runs=1,
        slots=(chained,),
    )
    assert len(res_chain.ready_to_enqueue) == 0
    assert len(res_chain.promoted_to_next_strategy) == 1
    assert res_chain.promoted_to_next_strategy[0].strategy_id == "strat_2"
    assert res_chain.promoted_to_next_strategy[0].next_strategy_ids == ()


def test_rate_limit_bucket_monotonic_429_pause_and_pause_compensated_refill() -> None:
    t0 = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    bucket = RateLimitBucket(
        tenant_id="ten_1",
        rate_limit_key="itron_api",
        capacity=10,
        refill_per_second=1.0,
        tokens=2.0,
        refilled_at=t0,
    )

    # Consume 2 tokens -> succeeds with 0 remaining
    b1, ok1, _ = bucket.try_consume(2, t0)
    assert ok1
    assert b1.tokens == 0.0

    # Consume 3 tokens immediately -> rate-limited, returns requeue_after = t0 + 3s
    b2, ok2, requeue_after = b1.try_consume(3, t0)
    assert not ok2
    assert requeue_after == t0 + timedelta(seconds=3)

    # Apply upstream 429 Retry-After of 20s, then a shorter 5s -> GREATEST keeps 20s!
    b_paused = b2.apply_upstream_pause(timedelta(seconds=20), t0)
    b_paused = b_paused.apply_upstream_pause(timedelta(seconds=5), t0)
    assert b_paused.paused_until == t0 + timedelta(seconds=20)

    # At t0 + 25s (5 seconds after the 20s pause expired), settle_and_refill shifts refilled_at
    # by the 20s pause duration so only 5 tokens refill (not 25)!
    b_settled = b_paused.settle_and_refill(t0 + timedelta(seconds=25))
    assert b_settled.paused_until is None
    assert b_settled.tokens == 5.0


def test_fair_queue_selector_prevents_noisy_neighbor_starvation() -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    # Tenant A floods 50 items; Tenant B has 1 item; Tenant C has 1 item
    items: list[QueueItem] = [
        QueueItem(
            id=idx,
            tenant_id="tenant_a",
            run_id=f"run_a_{idx}",
            step_run_id=f"stp_a_{idx}",
            step_created_at=now,
            retry_count=0,
            item_kind=QueueItemKind.EXECUTE,
            queue_name="default",
            priority=Priority.REALTIME,
            available_at=now,
            enqueued_at=now,
        )
        for idx in range(1, 51)
    ]
    items.append(
        QueueItem(
            id=51,
            tenant_id="tenant_b",
            run_id="run_b_1",
            step_run_id="stp_b_1",
            step_created_at=now,
            retry_count=0,
            item_kind=QueueItemKind.EXECUTE,
            queue_name="default",
            priority=Priority.REALTIME,
            available_at=now,
            enqueued_at=now,
        )
    )
    items.append(
        QueueItem(
            id=52,
            tenant_id="tenant_c",
            run_id="run_c_1",
            step_run_id="stp_c_1",
            step_created_at=now,
            retry_count=0,
            item_kind=QueueItemKind.EXECUTE,
            queue_name="default",
            priority=Priority.REALTIME,
            available_at=now,
            enqueued_at=now,
        )
    )

    # With free_slots=3, rank 1 from each tenant is selected (tenant_a, tenant_b, tenant_c)!
    batch = FairQueueSelector.select_fair_batch(
        ready_items=items,
        last_serviced_tenant_id="",
        free_slots=3,
    )
    assert [i.tenant_id for i in batch.selected_items] == [
        "tenant_a",
        "tenant_b",
        "tenant_c",
    ]
    assert batch.next_cursor_tenant_id == "tenant_c"
