"""Hatchet v1 Scheduling, Window-Function Concurrency Evaluation, Rate-Limit Buckets, and Fair Dequeue."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from orchestration.domain.constants import ConcurrencyStrategy, Priority, QueueItemKind


@dataclass(frozen=True)
class ConcurrencySlot:
    """Unified concurrency slot representing either a queued (`is_filled=False`) or active (`is_filled=True`) step."""

    sort_id: int
    tenant_id: str
    strategy_id: str
    concurrency_key: str
    run_id: str
    step_run_id: str
    step_created_at: datetime
    retry_count: int
    priority: Priority = Priority.REALTIME
    is_filled: bool = False
    next_strategy_ids: tuple[str, ...] = ()
    queue_name: str = "default"
    rate_limit_key: str | None = None
    rate_limit_units: int = 1
    acquired_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ConcurrencyEvaluationResult:
    """Deterministic output of evaluating a Hatchet window-function concurrency strategy."""

    newly_filled_slots: tuple[ConcurrencySlot, ...]
    promoted_to_next_strategy: tuple[ConcurrencySlot, ...]
    ready_to_enqueue: tuple[ConcurrencySlot, ...]
    cancelled_slots: tuple[ConcurrencySlot, ...]
    remaining_waiting_slots: tuple[ConcurrencySlot, ...]


class ConcurrencyWindowEvaluator:
    """Pure Hatchet v1 window-function concurrency evaluator (`pkg/repository/sqlcv1/concurrency.sql`).

    Governs both active (`is_filled=True`) and queued (`is_filled=False`) slots in a single pass
    and supports multi-strategy chaining via `next_strategy_ids`.
    """

    @staticmethod
    def evaluate_key_group(
        *,
        strategy: ConcurrencyStrategy,
        max_runs: int,
        slots: Sequence[ConcurrencySlot],
        now: datetime | None = None,
    ) -> ConcurrencyEvaluationResult:
        timestamp = now or datetime.now(UTC)
        ordered_asc = sorted(slots, key=lambda s: s.sort_id)

        if strategy in (
            ConcurrencyStrategy.SERIAL,
            ConcurrencyStrategy.GROUP_ROUND_ROBIN,
        ):
            newly_filled, cancelled, remaining = ConcurrencyWindowEvaluator._eval_fifo_fill(
                ordered_asc, max_runs, timestamp
            )
        elif strategy == ConcurrencyStrategy.CANCEL_IN_PROGRESS:
            newly_filled, cancelled, remaining = (
                ConcurrencyWindowEvaluator._eval_cancel_in_progress(
                    ordered_asc, max_runs, timestamp
                )
            )
        elif strategy == ConcurrencyStrategy.CANCEL_NEWEST:
            newly_filled, cancelled, remaining = ConcurrencyWindowEvaluator._eval_cancel_newest(
                ordered_asc, max_runs, timestamp
            )
        elif strategy == ConcurrencyStrategy.COALESCE_LATEST:
            newly_filled, cancelled, remaining = ConcurrencyWindowEvaluator._eval_coalesce_latest(
                ordered_asc, max_runs, timestamp
            )
        else:
            newly_filled, cancelled, remaining = (
                ConcurrencyWindowEvaluator._eval_cancel_queued_except_oldest(
                    ordered_asc, max_runs, timestamp
                )
            )

        promoted_next, ready_enqueue = ConcurrencyWindowEvaluator._partition_newly_filled(
            newly_filled
        )

        return ConcurrencyEvaluationResult(
            newly_filled_slots=tuple(newly_filled),
            promoted_to_next_strategy=tuple(promoted_next),
            ready_to_enqueue=tuple(ready_enqueue),
            cancelled_slots=tuple(cancelled),
            remaining_waiting_slots=tuple(remaining),
        )

    @staticmethod
    def _eval_fifo_fill(
        ordered_asc: list[ConcurrencySlot],
        max_runs: int,
        timestamp: datetime,
    ) -> tuple[list[ConcurrencySlot], list[ConcurrencySlot], list[ConcurrencySlot]]:
        newly_filled: list[ConcurrencySlot] = []
        remaining: list[ConcurrencySlot] = []
        active_count = sum(1 for s in ordered_asc if s.is_filled)
        available_capacity = max(0, max_runs - active_count)
        for slot in ordered_asc:
            if slot.is_filled:
                continue
            if available_capacity > 0:
                newly_filled.append(replace(slot, is_filled=True, acquired_at=timestamp))
                available_capacity -= 1
            else:
                remaining.append(slot)
        return newly_filled, [], remaining

    @staticmethod
    def _eval_cancel_in_progress(
        ordered_asc: list[ConcurrencySlot],
        max_runs: int,
        timestamp: datetime,
    ) -> tuple[list[ConcurrencySlot], list[ConcurrencySlot], list[ConcurrencySlot]]:
        newly_filled: list[ConcurrencySlot] = []
        cancelled: list[ConcurrencySlot] = []
        ordered_desc = list(reversed(ordered_asc))
        for idx, slot in enumerate(ordered_desc):
            if idx < max_runs:
                if not slot.is_filled:
                    newly_filled.append(replace(slot, is_filled=True, acquired_at=timestamp))
            else:
                cancelled.append(slot)
        return newly_filled, cancelled, []

    @staticmethod
    def _eval_cancel_newest(
        ordered_asc: list[ConcurrencySlot],
        max_runs: int,
        timestamp: datetime,
    ) -> tuple[list[ConcurrencySlot], list[ConcurrencySlot], list[ConcurrencySlot]]:
        newly_filled: list[ConcurrencySlot] = []
        cancelled: list[ConcurrencySlot] = []
        for idx, slot in enumerate(ordered_asc):
            if idx < max_runs:
                if not slot.is_filled:
                    newly_filled.append(replace(slot, is_filled=True, acquired_at=timestamp))
            else:
                cancelled.append(slot)
        return newly_filled, cancelled, []

    @staticmethod
    def _eval_coalesce_latest(
        ordered_asc: list[ConcurrencySlot],
        max_runs: int,
        timestamp: datetime,
    ) -> tuple[list[ConcurrencySlot], list[ConcurrencySlot], list[ConcurrencySlot]]:
        newly_filled: list[ConcurrencySlot] = []
        cancelled: list[ConcurrencySlot] = []
        remaining: list[ConcurrencySlot] = []
        active_slots = [s for s in ordered_asc if s.is_filled]
        waiting_slots = [s for s in ordered_asc if not s.is_filled]
        available_capacity = max(0, max_runs - len(active_slots))

        if available_capacity > 0 and waiting_slots:
            winners = waiting_slots[-available_capacity:]
            superseded = waiting_slots[:-available_capacity]
            for w in winners:
                newly_filled.append(replace(w, is_filled=True, acquired_at=timestamp))
            cancelled.extend(superseded)
        elif len(waiting_slots) > max_runs:
            remaining.extend(waiting_slots[-max_runs:])
            cancelled.extend(waiting_slots[:-max_runs])
        else:
            remaining.extend(waiting_slots)
        return newly_filled, cancelled, remaining

    @staticmethod
    def _eval_cancel_queued_except_oldest(
        ordered_asc: list[ConcurrencySlot],
        max_runs: int,
        timestamp: datetime,
    ) -> tuple[list[ConcurrencySlot], list[ConcurrencySlot], list[ConcurrencySlot]]:
        newly_filled: list[ConcurrencySlot] = []
        cancelled: list[ConcurrencySlot] = []
        remaining: list[ConcurrencySlot] = []
        active_slots = [s for s in ordered_asc if s.is_filled]
        waiting_slots = [s for s in ordered_asc if not s.is_filled]
        available_capacity = max(0, max_runs - len(active_slots))

        for slot in waiting_slots:
            if available_capacity > 0:
                newly_filled.append(replace(slot, is_filled=True, acquired_at=timestamp))
                available_capacity -= 1
            elif len(remaining) < max_runs:
                remaining.append(slot)
            else:
                cancelled.append(slot)
        return newly_filled, cancelled, remaining

    @staticmethod
    def _partition_newly_filled(
        newly_filled: list[ConcurrencySlot],
    ) -> tuple[list[ConcurrencySlot], list[ConcurrencySlot]]:
        promoted_next: list[ConcurrencySlot] = []
        ready_enqueue: list[ConcurrencySlot] = []
        for filled in newly_filled:
            if filled.next_strategy_ids:
                next_strat = filled.next_strategy_ids[0]
                rest_strats = filled.next_strategy_ids[1:]
                promoted_next.append(
                    replace(
                        filled,
                        strategy_id=next_strat,
                        next_strategy_ids=rest_strats,
                        is_filled=False,
                        acquired_at=None,
                    )
                )
            else:
                ready_enqueue.append(filled)
        return promoted_next, ready_enqueue


@dataclass(frozen=True)
class RateLimitBucket:
    """Token-bucket rate limit state with Hatchet v1 monotonic 429 pause and pause-compensated refill."""

    tenant_id: str
    rate_limit_key: str
    capacity: int
    refill_per_second: float
    tokens: float
    refilled_at: datetime
    paused_at: datetime | None = None
    paused_until: datetime | None = None

    def is_paused(self, now: datetime) -> bool:
        return self.paused_until is not None and now < self.paused_until

    def settle_and_refill(self, now: datetime) -> RateLimitBucket:
        """Settle expired pauses (shifting refilled_at by pause duration per Hatchet SettleExpiredRateLimitPauses)
        and refill tokens proportionally up to capacity.
        """
        effective_refilled_at = self.refilled_at
        paused_at = self.paused_at
        paused_until = self.paused_until

        if paused_until is not None and now >= paused_until:
            if paused_at is not None and paused_until > paused_at:
                effective_refilled_at = effective_refilled_at + (paused_until - paused_at)
            paused_at = None
            paused_until = None

        if paused_until is not None and now < paused_until:
            return self

        elapsed_seconds = max(0.0, (now - effective_refilled_at).total_seconds())
        added_tokens = elapsed_seconds * self.refill_per_second
        new_tokens = min(float(self.capacity), self.tokens + added_tokens)

        return replace(
            self,
            tokens=new_tokens,
            refilled_at=now,
            paused_at=paused_at,
            paused_until=paused_until,
        )

    def try_consume(
        self, units: int, now: datetime
    ) -> tuple[RateLimitBucket, bool, datetime | None]:
        """Attempt to consume `units` tokens.
        Returns `(updated_bucket, consumed_ok, requeue_after_if_rate_limited)`.
        """
        refilled = self.settle_and_refill(now)
        if refilled.is_paused(now):
            return refilled, False, refilled.paused_until

        if refilled.tokens >= units:
            return (
                replace(refilled, tokens=refilled.tokens - units),
                True,
                None,
            )

        deficit = units - refilled.tokens
        wait_seconds = (
            deficit / refilled.refill_per_second if refilled.refill_per_second > 0 else 60.0
        )
        requeue_after = now + timedelta(seconds=max(0.05, wait_seconds))
        return refilled, False, requeue_after

    def apply_upstream_pause(self, retry_after: timedelta, now: datetime) -> RateLimitBucket:
        """Apply an upstream 429 Retry-After pause monotonically (`GREATEST(paused_until, now + retry_after)`)."""
        candidate_until = now + retry_after
        new_paused_until = (
            max(self.paused_until, candidate_until)
            if self.paused_until is not None
            else candidate_until
        )
        new_paused_at = self.paused_at if self.paused_at is not None else now
        return replace(
            self,
            paused_at=new_paused_at,
            paused_until=new_paused_until,
        )


@dataclass(frozen=True)
class QueueItem:
    """Hot queue item in `workflow_queue_items`."""

    id: int
    tenant_id: str
    run_id: str
    step_run_id: str
    step_created_at: datetime
    retry_count: int
    item_kind: QueueItemKind
    queue_name: str
    priority: Priority
    available_at: datetime
    enqueued_at: datetime
    concurrency_key: str | None = None
    rate_limit_key: str | None = None
    rate_limit_units: int = 1


@dataclass(frozen=True)
class PausedQueueItem:
    """Parked queue item waiting for rate-limit refill or 429 Retry-After expiration (`workflow_paused_queue_items`)."""

    id: int
    tenant_id: str
    rate_limit_key: str
    run_id: str
    step_run_id: str
    step_created_at: datetime
    retry_count: int
    queue_name: str
    priority: Priority
    requeue_after: datetime
    concurrency_key: str | None = None
    rate_limit_units: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class FairDequeueResult:
    """Result of fair multi-tenant round-robin queue selection."""

    selected_items: tuple[QueueItem, ...]
    next_cursor_tenant_id: str
    min_unprocessed_id: int


class FairQueueSelector:
    """Pure implementation of §7.5.2 multi-tenant round-robin interleaving with rotated cursor advancement."""

    @staticmethod
    def select_fair_batch(
        *,
        ready_items: Sequence[QueueItem],
        last_serviced_tenant_id: str,
        free_slots: int,
        per_tenant_cap: int = 10,
        max_active_tenants: int = 50,
    ) -> FairDequeueResult:
        if not ready_items or free_slots <= 0:
            min_id = min((item.id for item in ready_items), default=0)
            return FairDequeueResult(
                selected_items=(),
                next_cursor_tenant_id=last_serviced_tenant_id,
                min_unprocessed_id=min_id,
            )

        distinct_tenants = sorted({item.tenant_id for item in ready_items})
        # Rotate tenants starting strictly after last_serviced_tenant_id
        rotated_tenants = sorted(
            distinct_tenants,
            key=lambda tid: (not (tid > last_serviced_tenant_id), tid),
        )[:max_active_tenants]

        tenant_order_index = {tid: idx for idx, tid in enumerate(rotated_tenants)}
        items_by_tenant: dict[str, list[QueueItem]] = {tid: [] for tid in rotated_tenants}
        for item in ready_items:
            if item.tenant_id in items_by_tenant:
                items_by_tenant[item.tenant_id].append(item)

        ranked_candidates: list[tuple[int, int, int, int, QueueItem]] = []
        for tid in rotated_tenants:
            sorted_tenant_items = sorted(
                items_by_tenant[tid],
                key=lambda x: (-int(x.priority), x.id),
            )[:per_tenant_cap]
            for rank_idx, item in enumerate(sorted_tenant_items, start=1):
                ranked_candidates.append(
                    (
                        rank_idx,
                        -int(item.priority),
                        tenant_order_index[tid],
                        item.id,
                        item,
                    )
                )

        # Interleave by tenant_rank ASC, priority DESC, rotated tenant order, id ASC
        ranked_candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2], entry[3]))
        selected = tuple(entry[4] for entry in ranked_candidates[:free_slots])

        if selected:
            # Advance cursor to the tenant of the last selected item in rotated tenant order
            selected_tenants_in_rotation = [
                tid for tid in rotated_tenants if any(item.tenant_id == tid for item in selected)
            ]
            next_cursor = selected_tenants_in_rotation[-1]
        else:
            next_cursor = last_serviced_tenant_id

        selected_ids = {item.id for item in selected}
        remaining_ids = [item.id for item in ready_items if item.id not in selected_ids]
        min_unprocessed = min(remaining_ids, default=0)

        return FairDequeueResult(
            selected_items=selected,
            next_cursor_tenant_id=next_cursor,
            min_unprocessed_id=min_unprocessed,
        )


__all__ = [
    "ConcurrencyEvaluationResult",
    "ConcurrencySlot",
    "ConcurrencyWindowEvaluator",
    "FairDequeueResult",
    "FairQueueSelector",
    "PausedQueueItem",
    "QueueItem",
    "RateLimitBucket",
]
