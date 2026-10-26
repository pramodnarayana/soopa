"""Outbound repository, queue, concurrency, rate-limit, payload store, and UoW protocols."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from seedwork.domain.types import JsonDict
from seedwork.uow import UnitOfWorkPort

from orchestration.domain.constants import (
    ConditionKind,
    IdempotencyEvictionPolicy,
    PayloadType,
    Priority,
    QueueItemKind,
)
from orchestration.domain.exceptions import (
    DuplicateIdempotencyKeyError,
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
    PausedQueueItem,
    QueueItem,
    RateLimitBucket,
)


class WorkflowRunRepositoryPort(Protocol):
    """Persistence port for WorkflowRun, StepRun, StepAttempt, and ActiveLease entities."""

    async def get_by_id(
        self, tenant_id: str, run_id: str
    ) -> Result[WorkflowRun, RunNotFoundError]: ...

    async def save(self, run: WorkflowRun) -> None: ...

    async def save_attempt(self, attempt: StepAttempt) -> None: ...

    async def acquire_lease(self, lease: ActiveLease) -> None: ...

    async def renew_lease(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
        retry_count: int,
        worker_id: str,
        lease_ttl: timedelta,
        now: datetime,
    ) -> Result[ActiveLease, WorkflowError]: ...

    async def release_lease(self, step_run_id: str) -> None: ...

    async def list_expired_leases(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[ActiveLease]: ...

    async def list_timed_out_leases(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[ActiveLease]: ...


class WorkflowMatchRepositoryPort(Protocol):
    """Persistence port for Hatchet v1 CNF WorkflowMatch and MatchCondition records."""

    async def save_matches(self, matches: Sequence[WorkflowMatch]) -> None: ...

    async def save_match(self, match: WorkflowMatch) -> None: ...

    async def list_by_run(self, tenant_id: str, run_id: str) -> Sequence[WorkflowMatch]: ...

    async def find_unsatisfied_for_event(
        self,
        *,
        tenant_id: str,
        condition_kind: ConditionKind,
        event_key: str,
        resource_hint: str | None = None,
    ) -> Sequence[WorkflowMatch]: ...

    async def list_expired_signal_waits(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[WorkflowMatch]: ...


class WorkflowQueuePort(Protocol):
    """Persistence port for the hot workflow_queue_items and workflow_paused_queue_items tables."""

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
    ) -> QueueItem: ...

    async def dequeue_fair_batch(
        self,
        *,
        queue_name: str,
        free_slots: int,
        now: datetime,
        per_tenant_cap: int = 10,
        max_active_tenants: int = 50,
    ) -> FairDequeueResult: ...

    async def park_rate_limited(
        self,
        *,
        item: QueueItem,
        rate_limit_key: str,
        requeue_after: datetime,
        now: datetime,
    ) -> PausedQueueItem: ...

    async def unpause_ready_items(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[PausedQueueItem]: ...

    async def remove_for_run(self, tenant_id: str, run_id: str) -> None: ...


class WorkflowConcurrencyPort(Protocol):
    """Persistence port for Hatchet v1 unified concurrency slots (`workflow_concurrency_slots`)."""

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
    ) -> ConcurrencySlot: ...

    async def list_slots_for_key(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
    ) -> Sequence[ConcurrencySlot]: ...

    async def apply_evaluation_result(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
        result: ConcurrencyEvaluationResult,
    ) -> None: ...

    async def release_slot_for_step(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
    ) -> Sequence[tuple[str, str]]:
        """Release active/waiting slots for a step and return affected `(strategy_id, concurrency_key)` pairs."""
        ...

    async def release_slots_for_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> Sequence[tuple[str, str]]: ...


class WorkflowRateLimitPort(Protocol):
    """Persistence port for token-bucket rate limit state (`workflow_rate_limit_buckets`)."""

    async def get_or_create_bucket(
        self,
        *,
        tenant_id: str,
        rate_limit_key: str,
        capacity: int,
        refill_per_second: float,
        now: datetime,
    ) -> RateLimitBucket: ...

    async def save_bucket(self, bucket: RateLimitBucket) -> None: ...


class WorkflowPayloadStorePort(Protocol):
    """Persistence port for decoupled payloads (`workflow_payloads`) with zero-copy reference resolution."""

    async def save_payload(self, record: PayloadRecord) -> None: ...

    async def get_payload(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        payload_type: PayloadType,
    ) -> PayloadRecord | None: ...

    async def resolve_step_input(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
    ) -> JsonDict: ...


class WorkflowIdempotencyPort(Protocol):
    """Persistence port for cross-partition idempotency claims (`workflow_idempotency_keys`)."""

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
    ) -> Result[IdempotencyKeyRecord, DuplicateIdempotencyKeyError]: ...

    async def release_on_terminal_status(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        run_id: str,
    ) -> None: ...


class WorkflowUnitOfWorkPort(UnitOfWorkPort, Protocol):
    """Transactional Unit of Work bundling all Workflow Engine outbound ports."""

    runs: WorkflowRunRepositoryPort
    matches: WorkflowMatchRepositoryPort
    queue: WorkflowQueuePort
    concurrency: WorkflowConcurrencyPort
    rate_limits: WorkflowRateLimitPort
    payloads: WorkflowPayloadStorePort
    idempotency: WorkflowIdempotencyPort


__all__ = [
    "WorkflowConcurrencyPort",
    "WorkflowIdempotencyPort",
    "WorkflowMatchRepositoryPort",
    "WorkflowPayloadStorePort",
    "WorkflowQueuePort",
    "WorkflowRateLimitPort",
    "WorkflowRunRepositoryPort",
    "WorkflowUnitOfWorkPort",
]
