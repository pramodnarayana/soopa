"""In-memory implementations of all Workflow Engine outbound ports for fast hexagonal testing."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import TracebackType

from database.outbox_serializer import serialize_domain_event
from seedwork.domain.types import JsonDict

from orchestration.domain.constants import (
    ConditionKind,
    IdempotencyEvictionPolicy,
    MatchKind,
    PayloadLocation,
    PayloadType,
    Priority,
    QueueItemKind,
    RunStatus,
    WorkflowErrorCode,
)
from orchestration.domain.exceptions import (
    DuplicateIdempotencyKeyError,
    FencingTokenMismatchError,
    Result,
    RunNotFoundError,
    WorkflowError,
)
from orchestration.domain.matching import WorkflowMatch
from orchestration.domain.run import (
    ActiveLease,
    IdempotencyKeyRecord,
    PayloadRecord,
    StepAttempt,
    WorkflowRun,
)
from orchestration.domain.scheduling import (
    ConcurrencyEvaluationResult,
    ConcurrencySlot,
    FairDequeueResult,
    FairQueueSelector,
    PausedQueueItem,
    QueueItem,
    RateLimitBucket,
)
from orchestration.ports.outbound.repository_ports import (
    WorkflowConcurrencyPort,
    WorkflowIdempotencyPort,
    WorkflowMatchRepositoryPort,
    WorkflowPayloadStorePort,
    WorkflowQueuePort,
    WorkflowRateLimitPort,
    WorkflowRunRepositoryPort,
    WorkflowUnitOfWorkPort,
)


class InMemoryWorkflowRunRepository(WorkflowRunRepositoryPort):
    """In-memory repository for WorkflowRun, StepAttempt, and ActiveLease."""

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], WorkflowRun] = {}
        self.attempts: list[StepAttempt] = []
        self.leases: dict[str, ActiveLease] = {}
        self.drained_events: list[JsonDict] = []

    async def get_by_id(self, tenant_id: str, run_id: str) -> Result[WorkflowRun, RunNotFoundError]:
        run = self.runs.get((tenant_id, run_id))
        if run is None:
            return Result.err(RunNotFoundError.for_id(run_id))
        return Result.ok(deepcopy(run))

    async def list_recent(
        self,
        tenant_id: str,
        *,
        workflow_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> Sequence[WorkflowRun]:
        matching = [
            deepcopy(run)
            for (tid, _rid), run in self.runs.items()
            if tid == tenant_id
            and (workflow_id is None or run.workflow_id == workflow_id)
            and (status is None or run.status == status)
        ]
        matching.sort(key=lambda r: r.created_at, reverse=True)
        return tuple(matching[:limit])

    async def save(self, run: WorkflowRun) -> None:
        for event in run.domain_events:
            self.drained_events.append(serialize_domain_event(event))
        run.clear_domain_events()
        self.runs[(run.tenant_id, run.id)] = deepcopy(run)

    async def save_attempt(self, attempt: StepAttempt) -> None:
        self.attempts = [a for a in self.attempts if a.id != attempt.id]
        self.attempts.append(attempt)

    async def acquire_lease(self, lease: ActiveLease) -> None:
        self.leases[lease.step_run_id] = lease

    async def renew_lease(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
        retry_count: int,
        worker_id: str,
        lease_ttl: timedelta,
        now: datetime,
    ) -> Result[ActiveLease, WorkflowError]:
        lease = self.leases.get(step_run_id)
        if lease is None or lease.tenant_id != tenant_id:
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.STEP_NOT_FOUND,
                    message=f"Active lease for step '{step_run_id}' not found.",
                )
            )
        if lease.retry_count != retry_count or lease.worker_id != worker_id:
            return Result.err(
                FencingTokenMismatchError.for_step(
                    step_run_id=step_run_id,
                    expected_retry_count=lease.retry_count,
                    actual_retry_count=retry_count,
                )
            )
        renewed = replace(lease, lease_expires_at=now + lease_ttl)
        self.leases[step_run_id] = renewed
        return Result.ok(renewed)

    async def release_lease(self, step_run_id: str) -> None:
        self.leases.pop(step_run_id, None)

    async def list_expired_leases(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[ActiveLease]:
        expired = [lease for lease in self.leases.values() if lease.is_lease_expired(now)]
        return tuple(expired[:limit])

    async def list_timed_out_leases(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[ActiveLease]:
        timed_out = [lease for lease in self.leases.values() if lease.is_timed_out(now)]
        return tuple(timed_out[:limit])


class InMemoryWorkflowMatchRepository(WorkflowMatchRepositoryPort):
    """In-memory repository for CNF WorkflowMatch records."""

    def __init__(self) -> None:
        self.matches: dict[str, WorkflowMatch] = {}

    async def save_matches(self, matches: Sequence[WorkflowMatch]) -> None:
        for match in matches:
            self.matches[match.id] = match

    async def save_match(self, match: WorkflowMatch) -> None:
        self.matches[match.id] = match

    async def list_by_run(self, tenant_id: str, run_id: str) -> Sequence[WorkflowMatch]:
        return tuple(
            m for m in self.matches.values() if m.tenant_id == tenant_id and m.run_id == run_id
        )

    async def find_unsatisfied_for_event(
        self,
        *,
        tenant_id: str,
        condition_kind: ConditionKind,
        event_key: str,
        resource_hint: str | None = None,
    ) -> Sequence[WorkflowMatch]:
        results: list[WorkflowMatch] = []
        for match in self.matches.values():
            if match.is_satisfied or match.tenant_id != tenant_id:
                continue
            for cond in match.conditions:
                if (
                    not cond.is_satisfied
                    and cond.condition_kind == condition_kind
                    and cond.event_key == event_key
                    and (
                        cond.event_resource_hint is None
                        or cond.event_resource_hint == resource_hint
                    )
                ):
                    results.append(match)
                    break
        return tuple(results)

    async def list_expired_signal_waits(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[WorkflowMatch]:
        expired: list[WorkflowMatch] = []
        for match in self.matches.values():
            if match.is_satisfied or match.kind != MatchKind.SIGNAL_WAIT:
                continue
            if any(c.timeout_at is not None and now >= c.timeout_at for c in match.conditions):
                expired.append(match)
        return tuple(expired[:limit])


class InMemoryWorkflowQueue(WorkflowQueuePort):
    """In-memory hot queue and paused rate-limit queue with fair multi-tenant cursor tracking."""

    def __init__(self) -> None:
        self._next_id: int = 1
        self._next_paused_id: int = 1
        self.items: list[QueueItem] = []
        self.paused_items: list[PausedQueueItem] = []
        self.cursors: dict[str, str] = {}

    async def enqueue(
        self,
        *,
        tenant_id: str,
        run_id: str,
        step_run_id: str,
        step_created_at: datetime,
        retry_count: int,
        item_kind: QueueItemKind,
        queue_name: str,
        priority: Priority,
        available_at: datetime,
        concurrency_key: str | None = None,
        rate_limit_key: str | None = None,
        rate_limit_units: int = 1,
    ) -> QueueItem:
        item = QueueItem(
            id=self._next_id,
            tenant_id=tenant_id,
            run_id=run_id,
            step_run_id=step_run_id,
            step_created_at=step_created_at,
            retry_count=retry_count,
            item_kind=item_kind,
            queue_name=queue_name,
            priority=priority,
            available_at=available_at,
            enqueued_at=available_at,
            concurrency_key=concurrency_key,
            rate_limit_key=rate_limit_key,
            rate_limit_units=rate_limit_units,
        )
        self._next_id += 1
        self.items.append(item)
        return item

    async def dequeue_fair_batch(
        self,
        *,
        queue_name: str,
        free_slots: int,
        now: datetime,
        per_tenant_cap: int = 10,
        max_active_tenants: int = 50,
    ) -> FairDequeueResult:
        ready = [
            item
            for item in self.items
            if item.queue_name == queue_name and item.available_at <= now
        ]
        last_cursor = self.cursors.get(queue_name, "")
        res = FairQueueSelector.select_fair_batch(
            ready_items=ready,
            last_serviced_tenant_id=last_cursor,
            free_slots=free_slots,
            per_tenant_cap=per_tenant_cap,
            max_active_tenants=max_active_tenants,
        )
        selected_ids = {item.id for item in res.selected_items}
        self.items = [item for item in self.items if item.id not in selected_ids]
        self.cursors[queue_name] = res.next_cursor_tenant_id
        return res

    async def park_rate_limited(
        self,
        *,
        item: QueueItem,
        rate_limit_key: str,
        requeue_after: datetime,
        now: datetime,
    ) -> PausedQueueItem:
        paused = PausedQueueItem(
            id=self._next_paused_id,
            tenant_id=item.tenant_id,
            rate_limit_key=rate_limit_key,
            run_id=item.run_id,
            step_run_id=item.step_run_id,
            step_created_at=item.step_created_at,
            retry_count=item.retry_count,
            queue_name=item.queue_name,
            priority=item.priority,
            requeue_after=requeue_after,
            concurrency_key=item.concurrency_key,
            rate_limit_units=item.rate_limit_units,
            created_at=now,
        )
        self._next_paused_id += 1
        self.paused_items.append(paused)
        return paused

    async def unpause_ready_items(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[PausedQueueItem]:
        ready = [p for p in self.paused_items if p.requeue_after <= now][:limit]
        ready_ids = {p.id for p in ready}
        self.paused_items = [p for p in self.paused_items if p.id not in ready_ids]
        return tuple(ready)

    async def remove_for_run(self, tenant_id: str, run_id: str) -> None:
        self.items = [
            i for i in self.items if not (i.tenant_id == tenant_id and i.run_id == run_id)
        ]
        self.paused_items = [
            p for p in self.paused_items if not (p.tenant_id == tenant_id and p.run_id == run_id)
        ]


class InMemoryWorkflowConcurrency(WorkflowConcurrencyPort):
    """In-memory Hatchet v1 concurrency slot store."""

    def __init__(self) -> None:
        self._next_sort_id: int = 1
        self.slots: list[ConcurrencySlot] = []

    async def insert_slot(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
        run_id: str,
        step_run_id: str,
        step_created_at: datetime,
        retry_count: int,
        priority: Priority,
        next_strategy_ids: tuple[str, ...] = (),
        queue_name: str = "default",
        rate_limit_key: str | None = None,
        rate_limit_units: int = 1,
        now: datetime,
    ) -> ConcurrencySlot:
        slot = ConcurrencySlot(
            sort_id=self._next_sort_id,
            tenant_id=tenant_id,
            strategy_id=strategy_id,
            concurrency_key=concurrency_key,
            run_id=run_id,
            step_run_id=step_run_id,
            step_created_at=step_created_at,
            retry_count=retry_count,
            priority=priority,
            is_filled=False,
            next_strategy_ids=next_strategy_ids,
            queue_name=queue_name,
            rate_limit_key=rate_limit_key,
            rate_limit_units=rate_limit_units,
            created_at=now,
        )
        self._next_sort_id += 1
        self.slots.append(slot)
        return slot

    async def list_slots_for_key(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
    ) -> Sequence[ConcurrencySlot]:
        return tuple(
            s
            for s in self.slots
            if s.tenant_id == tenant_id
            and s.strategy_id == strategy_id
            and s.concurrency_key == concurrency_key
        )

    async def apply_evaluation_result(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
        result: ConcurrencyEvaluationResult,
    ) -> None:
        cancelled_ids = {s.sort_id for s in result.cancelled_slots}
        newly_filled_map = {s.sort_id: s for s in result.newly_filled_slots}

        updated: list[ConcurrencySlot] = []
        for s in self.slots:
            if (
                s.tenant_id == tenant_id
                and s.strategy_id == strategy_id
                and s.concurrency_key == concurrency_key
            ):
                if s.sort_id in cancelled_ids:
                    continue
                if s.sort_id in newly_filled_map:
                    updated.append(newly_filled_map[s.sort_id])
                else:
                    updated.append(s)
            else:
                updated.append(s)
        self.slots = updated

    async def release_slot_for_step(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
    ) -> Sequence[tuple[str, str]]:
        affected: list[tuple[str, str]] = []
        remaining: list[ConcurrencySlot] = []
        for s in self.slots:
            if s.tenant_id == tenant_id and s.step_run_id == step_run_id:
                pair = (s.strategy_id, s.concurrency_key)
                if pair not in affected:
                    affected.append(pair)
            else:
                remaining.append(s)
        self.slots = remaining
        return tuple(affected)

    async def release_slots_for_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> Sequence[tuple[str, str]]:
        affected: list[tuple[str, str]] = []
        remaining: list[ConcurrencySlot] = []
        for s in self.slots:
            if s.tenant_id == tenant_id and s.run_id == run_id:
                pair = (s.strategy_id, s.concurrency_key)
                if pair not in affected:
                    affected.append(pair)
            else:
                remaining.append(s)
        self.slots = remaining
        return tuple(affected)


class InMemoryWorkflowRateLimit(WorkflowRateLimitPort):
    """In-memory token-bucket rate limit store."""

    def __init__(self) -> None:
        self.buckets: dict[tuple[str, str], RateLimitBucket] = {}

    async def get_or_create_bucket(
        self,
        *,
        tenant_id: str,
        rate_limit_key: str,
        capacity: int,
        refill_per_second: float,
        now: datetime,
    ) -> RateLimitBucket:
        key = (tenant_id, rate_limit_key)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = RateLimitBucket(
                tenant_id=tenant_id,
                rate_limit_key=rate_limit_key,
                capacity=capacity,
                refill_per_second=refill_per_second,
                tokens=float(capacity),
                refilled_at=now,
            )
            self.buckets[key] = bucket
        return bucket

    async def save_bucket(self, bucket: RateLimitBucket) -> None:
        self.buckets[(bucket.tenant_id, bucket.rate_limit_key)] = bucket


class InMemoryWorkflowPayloadStore(WorkflowPayloadStorePort):
    """In-memory decoupled payload store supporting zero-copy `PayloadLocation.REFERENCE` resolution."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, PayloadType], PayloadRecord] = {}

    async def save_payload(self, record: PayloadRecord) -> None:
        self.records[(record.tenant_id, record.owner_id, record.payload_type)] = record

    async def get_payload(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        payload_type: PayloadType,
    ) -> PayloadRecord | None:
        return self.records.get((tenant_id, owner_id, payload_type))

    async def resolve_step_input(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
    ) -> JsonDict:
        rec = self.records.get((tenant_id, step_run_id, PayloadType.STEP_INPUT))
        if rec is None:
            return {}
        if rec.location == PayloadLocation.INLINE and rec.inline_content is not None:
            return dict(rec.inline_content)
        if rec.location == PayloadLocation.REFERENCE and rec.payload_reference_id is not None:
            ref_rec = self.records.get((tenant_id, rec.payload_reference_id, PayloadType.RUN_INPUT))
            if ref_rec is not None and ref_rec.inline_content is not None:
                return dict(ref_rec.inline_content)
        return {}


class InMemoryWorkflowIdempotency(WorkflowIdempotencyPort):
    """In-memory cross-partition idempotency store."""

    def __init__(self) -> None:
        self.claims: dict[tuple[str, str, str], IdempotencyKeyRecord] = {}

    async def try_claim_key(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        key: str,
        run_id: str,
        eviction_policy: IdempotencyEvictionPolicy,
        ttl: timedelta,
        now: datetime,
    ) -> Result[IdempotencyKeyRecord, DuplicateIdempotencyKeyError]:
        map_key = (tenant_id, workflow_id, key)
        existing = self.claims.get(map_key)
        if existing is not None and not existing.is_expired(now):
            return Result.err(
                DuplicateIdempotencyKeyError.for_key(
                    workflow_id=workflow_id,
                    idempotency_key=key,
                    existing_run_id=existing.claimed_by_run_id,
                )
            )
        record = IdempotencyKeyRecord(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            key=key,
            claimed_by_run_id=run_id,
            eviction_policy=eviction_policy,
            expires_at=now + ttl,
            updated_at=now,
        )
        self.claims[map_key] = record
        return Result.ok(record)

    async def release_on_terminal_status(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        run_id: str,
    ) -> None:
        to_delete = [
            k
            for k, rec in self.claims.items()
            if rec.tenant_id == tenant_id
            and rec.workflow_id == workflow_id
            and rec.claimed_by_run_id == run_id
            and rec.eviction_policy == IdempotencyEvictionPolicy.ON_TERMINAL_STATUS
        ]
        for k in to_delete:
            self.claims.pop(k, None)


class InMemoryWorkflowUnitOfWork(WorkflowUnitOfWorkPort):
    """In-memory Unit of Work sharing repository state across use case calls in tests."""

    def __init__(
        self,
        *,
        runs: InMemoryWorkflowRunRepository | None = None,
        matches: InMemoryWorkflowMatchRepository | None = None,
        queue: InMemoryWorkflowQueue | None = None,
        concurrency: InMemoryWorkflowConcurrency | None = None,
        rate_limits: InMemoryWorkflowRateLimit | None = None,
        payloads: InMemoryWorkflowPayloadStore | None = None,
        idempotency: InMemoryWorkflowIdempotency | None = None,
    ) -> None:
        self.runs = runs or InMemoryWorkflowRunRepository()
        self.matches = matches or InMemoryWorkflowMatchRepository()
        self.queue = queue or InMemoryWorkflowQueue()
        self.concurrency = concurrency or InMemoryWorkflowConcurrency()
        self.rate_limits = rate_limits or InMemoryWorkflowRateLimit()
        self.payloads = payloads or InMemoryWorkflowPayloadStore()
        self.idempotency = idempotency or InMemoryWorkflowIdempotency()
        self.committed: bool = False

    async def __aenter__(self) -> InMemoryWorkflowUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.committed = False


__all__ = [
    "InMemoryWorkflowConcurrency",
    "InMemoryWorkflowIdempotency",
    "InMemoryWorkflowMatchRepository",
    "InMemoryWorkflowPayloadStore",
    "InMemoryWorkflowQueue",
    "InMemoryWorkflowRateLimit",
    "InMemoryWorkflowRunRepository",
    "InMemoryWorkflowUnitOfWork",
]
