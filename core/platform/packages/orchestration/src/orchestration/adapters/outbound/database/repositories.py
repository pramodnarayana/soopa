"""SQLAlchemy repository adapters with explicit static Data Mappers for the Durable Workflow Engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from database.outbox_serializer import serialize_domain_event
from database.repository import BaseSqlAlchemyRepository, HasDomainEvents
from seedwork.domain.types import JsonDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.adapters.outbound.database.models import (
    WorkflowActiveLeaseModel,
    WorkflowConcurrencySlotModel,
    WorkflowIdempotencyKeyModel,
    WorkflowMatchConditionModel,
    WorkflowMatchModel,
    WorkflowPausedQueueItemModel,
    WorkflowPayloadModel,
    WorkflowQueueCursorModel,
    WorkflowQueueItemModel,
    WorkflowRateLimitBucketModel,
    WorkflowRunModel,
    WorkflowStepAttemptModel,
    WorkflowStepRunModel,
)
from orchestration.domain.constants import (
    AttemptStatus,
    ConditionKind,
    IdempotencyEvictionPolicy,
    MatchAction,
    MatchKind,
    PayloadLocation,
    PayloadType,
    Priority,
    QueueItemKind,
    RunStatus,
    StepStatus,
    WorkflowErrorCode,
)
from orchestration.domain.exceptions import (
    DuplicateIdempotencyKeyError,
    FencingTokenMismatchError,
    Result,
    RunNotFoundError,
    WorkflowError,
)
from orchestration.domain.matching import MatchCondition, WorkflowMatch
from orchestration.domain.run import (
    ActiveLease,
    IdempotencyKeyRecord,
    PayloadRecord,
    StepAttempt,
    StepRun,
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
)


class SqlAlchemyWorkflowRunRepository(BaseSqlAlchemyRepository, WorkflowRunRepositoryPort):
    """SQLAlchemy adapter for WorkflowRun, StepRun, StepAttempt, and ActiveLease."""

    def __init__(
        self,
        session: AsyncSession,
        outbox_sink: Callable[[str, str, str | None, JsonDict], None] | None = None,
    ) -> None:
        super().__init__(session)
        self._session = session
        self._outbox_sink = outbox_sink
        self.drained_events: list[JsonDict] = []

    def _drain_events(
        self,
        aggregate: HasDomainEvents,
        default_tenant_id: str = "",
    ) -> None:
        """Extracts aggregate domain events using the centralized platform `serialize_domain_event` utility."""
        for event in aggregate.domain_events:
            serialized = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or default_tenant_id
            if self._outbox_sink is not None:
                self._outbox_sink(
                    tenant_id,
                    event.event_name,
                    event.idempotency_key,
                    serialized,
                )
            self.drained_events.append(serialized)
        aggregate.clear_domain_events()

    async def get_by_id(
        self, tenant_id: str, run_id: str
    ) -> Result[WorkflowRun, RunNotFoundError]:
        run_stmt = select(WorkflowRunModel).where(
            WorkflowRunModel.tenant_id == tenant_id,
            WorkflowRunModel.id == run_id,
        )
        run_record = (await self._session.execute(run_stmt)).scalar_one_or_none()
        if run_record is None:
            return Result.err(RunNotFoundError.for_id(run_id))

        step_stmt = select(WorkflowStepRunModel).where(
            WorkflowStepRunModel.tenant_id == tenant_id,
            WorkflowStepRunModel.run_id == run_id,
        )
        step_records = (await self._session.execute(step_stmt)).scalars().all()
        return Result.ok(self._to_domain_model(run_record, step_records))

    async def save(self, run: WorkflowRun) -> None:
        existing_stmt = select(WorkflowRunModel).where(
            WorkflowRunModel.tenant_id == run.tenant_id,
            WorkflowRunModel.id == run.id,
        )
        existing_run = (await self._session.execute(existing_stmt)).scalar_one_or_none()
        if existing_run is None:
            self._session.add(self._to_orm_model(run))
        else:
            self._update_record_from_domain(existing_run, run)

        step_stmt = select(WorkflowStepRunModel).where(
            WorkflowStepRunModel.tenant_id == run.tenant_id,
            WorkflowStepRunModel.run_id == run.id,
        )
        existing_steps = {
            rec.node_key: rec
            for rec in (await self._session.execute(step_stmt)).scalars().all()
        }
        for node_key, step in run.steps.items():
            existing_step = existing_steps.get(node_key)
            if existing_step is None:
                self._session.add(self._step_to_orm_model(step))
            else:
                self._update_step_record_from_domain(existing_step, step)

        self._drain_events(run, default_tenant_id=run.tenant_id)

    async def save_attempt(self, attempt: StepAttempt) -> None:
        stmt = select(WorkflowStepAttemptModel).where(
            WorkflowStepAttemptModel.id == attempt.id
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            self._session.add(self._attempt_to_orm_model(attempt))
        else:
            self._update_attempt_record_from_domain(existing, attempt)

    async def acquire_lease(self, lease: ActiveLease) -> None:
        await self.release_lease(lease.step_run_id)
        self._session.add(self._lease_to_orm_model(lease))

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
        stmt = select(WorkflowActiveLeaseModel).where(
            WorkflowActiveLeaseModel.tenant_id == tenant_id,
            WorkflowActiveLeaseModel.step_run_id == step_run_id,
        )
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        if record is None:
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.STEP_NOT_FOUND,
                    message=f"Active lease for step '{step_run_id}' not found.",
                )
            )
        if record.retry_count != retry_count or record.worker_id != worker_id:
            return Result.err(
                FencingTokenMismatchError.for_step(
                    step_run_id=step_run_id,
                    expected_retry_count=record.retry_count,
                    actual_retry_count=retry_count,
                )
            )
        record.lease_expires_at = now + lease_ttl
        return Result.ok(self._lease_to_domain_model(record))

    async def release_lease(self, step_run_id: str) -> None:
        await self._session.execute(
            delete(WorkflowActiveLeaseModel).where(
                WorkflowActiveLeaseModel.step_run_id == step_run_id
            )
        )

    async def list_expired_leases(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[ActiveLease]:
        stmt = (
            select(WorkflowActiveLeaseModel)
            .where(WorkflowActiveLeaseModel.lease_expires_at <= now)
            .limit(limit)
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return tuple(self._lease_to_domain_model(r) for r in records)

    async def list_timed_out_leases(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[ActiveLease]:
        stmt = (
            select(WorkflowActiveLeaseModel)
            .where(WorkflowActiveLeaseModel.timeout_at <= now)
            .limit(limit)
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return tuple(self._lease_to_domain_model(r) for r in records)

    @staticmethod
    def _to_orm_model(run: WorkflowRun) -> WorkflowRunModel:
        return WorkflowRunModel(
            id=run.id,
            tenant_id=run.tenant_id,
            workflow_id=run.workflow_id,
            workflow_version=run.workflow_version,
            status=run.status.value,
            priority=int(run.priority),
            concurrency_key=run.concurrency_key,
            idempotency_key=run.idempotency_key,
            parent_run_id=run.parent_run_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            failure_code=run.failure_code,
            failure_detail=run.failure_detail,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: WorkflowRunModel, run: WorkflowRun
    ) -> None:
        record.status = run.status.value
        record.priority = int(run.priority)
        record.concurrency_key = run.concurrency_key
        record.failure_code = run.failure_code
        record.failure_detail = run.failure_detail
        record.started_at = run.started_at
        record.finished_at = run.finished_at

    @staticmethod
    def _to_domain_model(
        record: WorkflowRunModel,
        step_records: Sequence[WorkflowStepRunModel],
    ) -> WorkflowRun:
        steps = {
            s.node_key: SqlAlchemyWorkflowRunRepository._step_to_domain_model(s)
            for s in step_records
        }
        return WorkflowRun(
            id=record.id,
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            workflow_version=record.workflow_version,
            status=RunStatus(record.status),
            priority=Priority(record.priority),
            concurrency_key=record.concurrency_key,
            idempotency_key=record.idempotency_key,
            parent_run_id=record.parent_run_id,
            trace_id=record.trace_id,
            correlation_id=record.correlation_id,
            failure_code=record.failure_code,
            failure_detail=record.failure_detail,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            steps=steps,
        )

    @staticmethod
    def _step_to_orm_model(step: StepRun) -> WorkflowStepRunModel:
        return WorkflowStepRunModel(
            id=step.id,
            run_id=step.run_id,
            run_created_at=step.run_created_at,
            tenant_id=step.tenant_id,
            node_key=step.node_key,
            status=step.status.value,
            retry_count=step.retry_count,
            app_retry_count=step.app_retry_count,
            internal_retry_count=step.internal_retry_count,
            failure_code=step.failure_code,
            failure_detail=step.failure_detail,
            created_at=step.created_at,
            finished_at=step.finished_at,
        )

    @staticmethod
    def _update_step_record_from_domain(
        record: WorkflowStepRunModel, step: StepRun
    ) -> None:
        record.status = step.status.value
        record.retry_count = step.retry_count
        record.app_retry_count = step.app_retry_count
        record.internal_retry_count = step.internal_retry_count
        record.failure_code = step.failure_code
        record.failure_detail = step.failure_detail
        record.finished_at = step.finished_at

    @staticmethod
    def _step_to_domain_model(record: WorkflowStepRunModel) -> StepRun:
        return StepRun(
            id=record.id,
            run_id=record.run_id,
            run_created_at=record.run_created_at,
            tenant_id=record.tenant_id,
            node_key=record.node_key,
            status=StepStatus(record.status),
            retry_count=record.retry_count,
            app_retry_count=record.app_retry_count,
            internal_retry_count=record.internal_retry_count,
            failure_code=record.failure_code,
            failure_detail=record.failure_detail,
            created_at=record.created_at,
            finished_at=record.finished_at,
        )

    @staticmethod
    def _attempt_to_orm_model(attempt: StepAttempt) -> WorkflowStepAttemptModel:
        return WorkflowStepAttemptModel(
            id=attempt.id,
            step_run_id=attempt.step_run_id,
            tenant_id=attempt.tenant_id,
            retry_count=attempt.retry_count,
            app_retry_count=attempt.app_retry_count,
            internal_retry_count=attempt.internal_retry_count,
            worker_id=attempt.worker_id,
            status=attempt.status.value,
            is_app_error=attempt.is_app_error,
            outcome_code=attempt.outcome_code,
            outcome_detail=attempt.outcome_detail,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
        )

    @staticmethod
    def _update_attempt_record_from_domain(
        record: WorkflowStepAttemptModel, attempt: StepAttempt
    ) -> None:
        record.status = attempt.status.value
        record.is_app_error = attempt.is_app_error
        record.outcome_code = attempt.outcome_code
        record.outcome_detail = attempt.outcome_detail
        record.finished_at = attempt.finished_at

    @staticmethod
    def _attempt_to_domain_model(record: WorkflowStepAttemptModel) -> StepAttempt:
        return StepAttempt(
            id=record.id,
            step_run_id=record.step_run_id,
            tenant_id=record.tenant_id,
            retry_count=record.retry_count,
            app_retry_count=record.app_retry_count,
            internal_retry_count=record.internal_retry_count,
            worker_id=record.worker_id,
            status=AttemptStatus(record.status),
            is_app_error=record.is_app_error,
            outcome_code=record.outcome_code,
            outcome_detail=record.outcome_detail,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )

    @staticmethod
    def _lease_to_orm_model(lease: ActiveLease) -> WorkflowActiveLeaseModel:
        return WorkflowActiveLeaseModel(
            step_run_id=lease.step_run_id,
            step_created_at=lease.step_created_at,
            retry_count=lease.retry_count,
            run_id=lease.run_id,
            tenant_id=lease.tenant_id,
            worker_id=lease.worker_id,
            lease_expires_at=lease.lease_expires_at,
            timeout_at=lease.timeout_at,
            evicted_at=lease.evicted_at,
        )

    @staticmethod
    def _lease_to_domain_model(record: WorkflowActiveLeaseModel) -> ActiveLease:
        return ActiveLease(
            step_run_id=record.step_run_id,
            step_created_at=record.step_created_at,
            retry_count=record.retry_count,
            run_id=record.run_id,
            tenant_id=record.tenant_id,
            worker_id=record.worker_id,
            lease_expires_at=record.lease_expires_at,
            timeout_at=record.timeout_at,
            evicted_at=record.evicted_at,
        )


class SqlAlchemyWorkflowMatchRepository(BaseSqlAlchemyRepository, WorkflowMatchRepositoryPort):
    """SQLAlchemy adapter for Hatchet v1 CNF WorkflowMatch and MatchCondition records."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

    async def save_matches(self, matches: Sequence[WorkflowMatch]) -> None:
        for match in matches:
            await self.save_match(match)

    async def save_match(self, match: WorkflowMatch) -> None:
        existing_stmt = select(WorkflowMatchModel).where(
            WorkflowMatchModel.id == match.id
        )
        existing_match = (await self._session.execute(existing_stmt)).scalar_one_or_none()
        if existing_match is None:
            self._session.add(self._to_orm_model(match))
        else:
            self._update_record_from_domain(existing_match, match)

        cond_stmt = select(WorkflowMatchConditionModel).where(
            WorkflowMatchConditionModel.match_id == match.id
        )
        existing_conds = {
            c.id: c for c in (await self._session.execute(cond_stmt)).scalars().all()
        }
        for cond in match.conditions:
            existing_cond = existing_conds.get(cond.id)
            if existing_cond is None:
                self._session.add(self._condition_to_orm_model(cond))
            else:
                self._update_condition_record_from_domain(existing_cond, cond)

    async def list_by_run(
        self, tenant_id: str, run_id: str
    ) -> Sequence[WorkflowMatch]:
        stmt = select(WorkflowMatchModel).where(
            WorkflowMatchModel.tenant_id == tenant_id,
            WorkflowMatchModel.run_id == run_id,
        )
        match_records = (await self._session.execute(stmt)).scalars().all()
        return await self._hydrate_matches(match_records)

    async def find_unsatisfied_for_event(
        self,
        *,
        tenant_id: str,
        condition_kind: ConditionKind,
        event_key: str,
        resource_hint: str | None = None,
    ) -> Sequence[WorkflowMatch]:
        cond_stmt = select(WorkflowMatchConditionModel.match_id).where(
            WorkflowMatchConditionModel.tenant_id == tenant_id,
            WorkflowMatchConditionModel.condition_kind == condition_kind.value,
            WorkflowMatchConditionModel.event_key == event_key,
            WorkflowMatchConditionModel.is_satisfied.is_(False),
        )
        match_ids = list({mid for mid in (await self._session.execute(cond_stmt)).scalars().all()})
        if not match_ids:
            return ()

        match_stmt = select(WorkflowMatchModel).where(
            WorkflowMatchModel.id.in_(match_ids),
            WorkflowMatchModel.is_satisfied.is_(False),
        )
        match_records = (await self._session.execute(match_stmt)).scalars().all()
        hydrated = await self._hydrate_matches(match_records)
        if resource_hint is None:
            return hydrated
        return tuple(
            m
            for m in hydrated
            if any(
                c.event_resource_hint is None or c.event_resource_hint == resource_hint
                for c in m.conditions
                if not c.is_satisfied
                and c.condition_kind == condition_kind
                and c.event_key == event_key
            )
        )

    async def list_expired_signal_waits(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[WorkflowMatch]:
        cond_stmt = (
            select(WorkflowMatchConditionModel.match_id)
            .where(
                WorkflowMatchConditionModel.is_satisfied.is_(False),
                WorkflowMatchConditionModel.timeout_at.is_not(None),
                WorkflowMatchConditionModel.timeout_at <= now,
            )
            .limit(limit)
        )
        match_ids = list({mid for mid in (await self._session.execute(cond_stmt)).scalars().all()})
        if not match_ids:
            return ()
        match_stmt = select(WorkflowMatchModel).where(
            WorkflowMatchModel.id.in_(match_ids),
            WorkflowMatchModel.is_satisfied.is_(False),
        )
        match_records = (await self._session.execute(match_stmt)).scalars().all()
        return await self._hydrate_matches(match_records)

    async def _hydrate_matches(
        self, match_records: Sequence[WorkflowMatchModel]
    ) -> Sequence[WorkflowMatch]:
        if not match_records:
            return ()
        ids = [m.id for m in match_records]
        cond_stmt = select(WorkflowMatchConditionModel).where(
            WorkflowMatchConditionModel.match_id.in_(ids)
        )
        all_conds = (await self._session.execute(cond_stmt)).scalars().all()
        conds_by_match: dict[str, list[WorkflowMatchConditionModel]] = {
            m.id: [] for m in match_records
        }
        for c in all_conds:
            if c.match_id in conds_by_match:
                conds_by_match[c.match_id].append(c)
        return tuple(
            self._to_domain_model(m, conds_by_match[m.id]) for m in match_records
        )

    @staticmethod
    def _to_orm_model(match: WorkflowMatch) -> WorkflowMatchModel:
        return WorkflowMatchModel(
            id=match.id,
            tenant_id=match.tenant_id,
            run_id=match.run_id,
            step_run_id=match.step_run_id,
            step_created_at=match.step_created_at,
            node_key=match.node_key,
            kind=match.kind.value,
            existing_data=dict(match.existing_data),
            is_satisfied=match.is_satisfied,
            resolved_action=(
                match.resolved_action.value
                if match.resolved_action is not None
                else None
            ),
            created_at=match.created_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: WorkflowMatchModel, match: WorkflowMatch
    ) -> None:
        record.existing_data = dict(match.existing_data)
        record.is_satisfied = match.is_satisfied
        record.resolved_action = (
            match.resolved_action.value
            if match.resolved_action is not None
            else None
        )

    @staticmethod
    def _to_domain_model(
        record: WorkflowMatchModel,
        cond_records: Sequence[WorkflowMatchConditionModel],
    ) -> WorkflowMatch:
        conditions = tuple(
            SqlAlchemyWorkflowMatchRepository._condition_to_domain_model(c)
            for c in cond_records
        )
        return WorkflowMatch(
            id=record.id,
            tenant_id=record.tenant_id,
            run_id=record.run_id,
            step_run_id=record.step_run_id,
            step_created_at=record.step_created_at,
            node_key=record.node_key,
            kind=MatchKind(record.kind),
            conditions=conditions,
            existing_data=dict(record.existing_data),
            is_satisfied=record.is_satisfied,
            resolved_action=(
                MatchAction(record.resolved_action)
                if record.resolved_action is not None
                else None
            ),
            created_at=record.created_at,
        )

    @staticmethod
    def _condition_to_orm_model(
        cond: MatchCondition,
    ) -> WorkflowMatchConditionModel:
        return WorkflowMatchConditionModel(
            match_id=cond.match_id,
            id=cond.id,
            tenant_id=cond.tenant_id,
            or_group_id=cond.or_group_id,
            condition_kind=cond.condition_kind.value,
            event_key=cond.event_key,
            event_resource_hint=cond.event_resource_hint,
            predicate_id=cond.predicate_id,
            readable_data_key=cond.readable_data_key,
            action=cond.action.value,
            is_satisfied=cond.is_satisfied,
            matched_data=(
                dict(cond.matched_data) if cond.matched_data is not None else None
            ),
            timeout_at=cond.timeout_at,
            created_at=cond.created_at,
        )

    @staticmethod
    def _update_condition_record_from_domain(
        record: WorkflowMatchConditionModel, cond: MatchCondition
    ) -> None:
        record.is_satisfied = cond.is_satisfied
        record.matched_data = (
            dict(cond.matched_data) if cond.matched_data is not None else None
        )

    @staticmethod
    def _condition_to_domain_model(
        record: WorkflowMatchConditionModel,
    ) -> MatchCondition:
        return MatchCondition(
            id=record.id,
            match_id=record.match_id,
            tenant_id=record.tenant_id,
            or_group_id=record.or_group_id,
            condition_kind=ConditionKind(record.condition_kind),
            event_key=record.event_key,
            event_resource_hint=record.event_resource_hint,
            predicate_id=record.predicate_id,
            readable_data_key=record.readable_data_key,
            action=MatchAction(record.action),
            is_satisfied=record.is_satisfied,
            matched_data=(
                dict(record.matched_data)
                if record.matched_data is not None
                else None
            ),
            timeout_at=record.timeout_at,
            created_at=record.created_at,
        )


class SqlAlchemyWorkflowQueueRepository(BaseSqlAlchemyRepository, WorkflowQueuePort):
    """SQLAlchemy adapter for hot workflow_queue_items and workflow_paused_queue_items."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

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
        record = WorkflowQueueItemModel(
            tenant_id=tenant_id,
            run_id=run_id,
            step_run_id=step_run_id,
            step_created_at=step_created_at,
            retry_count=retry_count,
            item_kind=item_kind.value,
            queue_name=queue_name,
            priority=int(priority),
            available_at=available_at,
            enqueued_at=available_at,
            concurrency_key=concurrency_key,
            rate_limit_key=rate_limit_key,
            rate_limit_units=rate_limit_units,
        )
        self._session.add(record)
        await self._session.flush()
        return self._to_domain_model(record)

    async def dequeue_fair_batch(
        self,
        *,
        queue_name: str,
        free_slots: int,
        now: datetime,
        per_tenant_cap: int = 10,
        max_active_tenants: int = 50,
    ) -> FairDequeueResult:
        cursor_stmt = select(WorkflowQueueCursorModel).where(
            WorkflowQueueCursorModel.queue_name == queue_name
        )
        cursor_rec = (await self._session.execute(cursor_stmt)).scalar_one_or_none()
        last_tenant = cursor_rec.last_serviced_tenant_id if cursor_rec is not None else ""

        ready_stmt = (
            select(WorkflowQueueItemModel)
            .where(
                WorkflowQueueItemModel.queue_name == queue_name,
                WorkflowQueueItemModel.available_at <= now,
            )
            .order_by(WorkflowQueueItemModel.id.asc())
            .with_for_update(skip_locked=True)
        )
        records = (await self._session.execute(ready_stmt)).scalars().all()
        domain_items = [self._to_domain_model(r) for r in records]

        res = FairQueueSelector.select_fair_batch(
            ready_items=domain_items,
            last_serviced_tenant_id=last_tenant,
            free_slots=free_slots,
            per_tenant_cap=per_tenant_cap,
            max_active_tenants=max_active_tenants,
        )
        selected_ids = [item.id for item in res.selected_items]
        if selected_ids:
            await self._session.execute(
                delete(WorkflowQueueItemModel).where(
                    WorkflowQueueItemModel.id.in_(selected_ids)
                )
            )
        if cursor_rec is None:
            self._session.add(
                WorkflowQueueCursorModel(
                    queue_name=queue_name,
                    last_serviced_tenant_id=res.next_cursor_tenant_id,
                    min_unprocessed_id=res.min_unprocessed_id,
                    updated_at=now,
                )
            )
        else:
            cursor_rec.last_serviced_tenant_id = res.next_cursor_tenant_id
            cursor_rec.min_unprocessed_id = res.min_unprocessed_id
            cursor_rec.updated_at = now
        return res

    async def park_rate_limited(
        self,
        *,
        item: QueueItem,
        rate_limit_key: str,
        requeue_after: datetime,
        now: datetime,
    ) -> PausedQueueItem:
        record = WorkflowPausedQueueItemModel(
            tenant_id=item.tenant_id,
            rate_limit_key=rate_limit_key,
            run_id=item.run_id,
            step_run_id=item.step_run_id,
            step_created_at=item.step_created_at,
            retry_count=item.retry_count,
            queue_name=item.queue_name,
            priority=int(item.priority),
            requeue_after=requeue_after,
            concurrency_key=item.concurrency_key,
            rate_limit_units=item.rate_limit_units,
            created_at=now,
        )
        self._session.add(record)
        await self._session.flush()
        return self._paused_to_domain_model(record)

    async def unpause_ready_items(
        self, *, now: datetime, limit: int = 100
    ) -> Sequence[PausedQueueItem]:
        stmt = (
            select(WorkflowPausedQueueItemModel)
            .where(WorkflowPausedQueueItemModel.requeue_after <= now)
            .order_by(WorkflowPausedQueueItemModel.requeue_after.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        records = (await self._session.execute(stmt)).scalars().all()
        if not records:
            return ()
        ids = [r.id for r in records]
        await self._session.execute(
            delete(WorkflowPausedQueueItemModel).where(
                WorkflowPausedQueueItemModel.id.in_(ids)
            )
        )
        return tuple(self._paused_to_domain_model(r) for r in records)

    async def remove_for_run(self, tenant_id: str, run_id: str) -> None:
        await self._session.execute(
            delete(WorkflowQueueItemModel).where(
                WorkflowQueueItemModel.tenant_id == tenant_id,
                WorkflowQueueItemModel.run_id == run_id,
            )
        )
        await self._session.execute(
            delete(WorkflowPausedQueueItemModel).where(
                WorkflowPausedQueueItemModel.tenant_id == tenant_id,
                WorkflowPausedQueueItemModel.run_id == run_id,
            )
        )

    @staticmethod
    def _to_domain_model(record: WorkflowQueueItemModel) -> QueueItem:
        return QueueItem(
            id=record.id,
            tenant_id=record.tenant_id,
            run_id=record.run_id,
            step_run_id=record.step_run_id,
            step_created_at=record.step_created_at,
            retry_count=record.retry_count,
            item_kind=QueueItemKind(record.item_kind),
            queue_name=record.queue_name,
            priority=Priority(record.priority),
            available_at=record.available_at,
            enqueued_at=record.enqueued_at,
            concurrency_key=record.concurrency_key,
            rate_limit_key=record.rate_limit_key,
            rate_limit_units=record.rate_limit_units,
        )

    @staticmethod
    def _paused_to_domain_model(
        record: WorkflowPausedQueueItemModel,
    ) -> PausedQueueItem:
        return PausedQueueItem(
            id=record.id,
            tenant_id=record.tenant_id,
            rate_limit_key=record.rate_limit_key,
            run_id=record.run_id,
            step_run_id=record.step_run_id,
            step_created_at=record.step_created_at,
            retry_count=record.retry_count,
            queue_name=record.queue_name,
            priority=Priority(record.priority),
            requeue_after=record.requeue_after,
            concurrency_key=record.concurrency_key,
            rate_limit_units=record.rate_limit_units,
            created_at=record.created_at,
        )


class SqlAlchemyWorkflowConcurrencyRepository(BaseSqlAlchemyRepository, WorkflowConcurrencyPort):
    """SQLAlchemy adapter for Hatchet v1 unified concurrency slots."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

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
        max_sort_stmt = select(
            func.coalesce(func.max(WorkflowConcurrencySlotModel.sort_id), 0)
        )
        current_max = int((await self._session.execute(max_sort_stmt)).scalar_one())
        next_sort_id = current_max + 1

        slot = ConcurrencySlot(
            sort_id=next_sort_id,
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
        self._session.add(self._to_orm_model(slot))
        await self._session.flush()
        return slot

    async def list_slots_for_key(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
    ) -> Sequence[ConcurrencySlot]:
        stmt = (
            select(WorkflowConcurrencySlotModel)
            .where(
                WorkflowConcurrencySlotModel.tenant_id == tenant_id,
                WorkflowConcurrencySlotModel.strategy_id == strategy_id,
                WorkflowConcurrencySlotModel.concurrency_key == concurrency_key,
            )
            .order_by(WorkflowConcurrencySlotModel.sort_id.asc())
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return tuple(self._to_domain_model(r) for r in records)

    async def apply_evaluation_result(
        self,
        *,
        tenant_id: str,
        strategy_id: str,
        concurrency_key: str,
        result: ConcurrencyEvaluationResult,
    ) -> None:
        evict_ids = [
            s.sort_id
            for s in (*result.cancelled_slots, *result.promoted_to_next_strategy)
        ]
        if evict_ids:
            await self._session.execute(
                delete(WorkflowConcurrencySlotModel).where(
                    WorkflowConcurrencySlotModel.tenant_id == tenant_id,
                    WorkflowConcurrencySlotModel.strategy_id == strategy_id,
                    WorkflowConcurrencySlotModel.concurrency_key == concurrency_key,
                    WorkflowConcurrencySlotModel.sort_id.in_(evict_ids),
                )
            )
        promoted_set = {s.sort_id for s in result.promoted_to_next_strategy}
        for filled in result.newly_filled_slots:
            if filled.sort_id in promoted_set:
                continue
            stmt = select(WorkflowConcurrencySlotModel).where(
                WorkflowConcurrencySlotModel.sort_id == filled.sort_id,
                WorkflowConcurrencySlotModel.tenant_id == tenant_id,
                WorkflowConcurrencySlotModel.strategy_id == strategy_id,
                WorkflowConcurrencySlotModel.step_run_id == filled.step_run_id,
            )
            rec = (await self._session.execute(stmt)).scalar_one_or_none()
            if rec is not None:
                self._update_record_from_domain(rec, filled)

    async def release_slot_for_step(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
    ) -> Sequence[tuple[str, str]]:
        stmt = select(WorkflowConcurrencySlotModel).where(
            WorkflowConcurrencySlotModel.tenant_id == tenant_id,
            WorkflowConcurrencySlotModel.step_run_id == step_run_id,
        )
        records = (await self._session.execute(stmt)).scalars().all()
        affected = list({(r.strategy_id, r.concurrency_key) for r in records})
        if records:
            await self._session.execute(
                delete(WorkflowConcurrencySlotModel).where(
                    WorkflowConcurrencySlotModel.tenant_id == tenant_id,
                    WorkflowConcurrencySlotModel.step_run_id == step_run_id,
                )
            )
        return tuple(affected)

    async def release_slots_for_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> Sequence[tuple[str, str]]:
        stmt = select(WorkflowConcurrencySlotModel).where(
            WorkflowConcurrencySlotModel.tenant_id == tenant_id,
            WorkflowConcurrencySlotModel.run_id == run_id,
        )
        records = (await self._session.execute(stmt)).scalars().all()
        affected = list({(r.strategy_id, r.concurrency_key) for r in records})
        if records:
            await self._session.execute(
                delete(WorkflowConcurrencySlotModel).where(
                    WorkflowConcurrencySlotModel.tenant_id == tenant_id,
                    WorkflowConcurrencySlotModel.run_id == run_id,
                )
            )
        return tuple(affected)

    @staticmethod
    def _to_orm_model(slot: ConcurrencySlot) -> WorkflowConcurrencySlotModel:
        return WorkflowConcurrencySlotModel(
            sort_id=slot.sort_id,
            tenant_id=slot.tenant_id,
            strategy_id=slot.strategy_id,
            concurrency_key=slot.concurrency_key,
            run_id=slot.run_id,
            step_run_id=slot.step_run_id,
            step_created_at=slot.step_created_at,
            retry_count=slot.retry_count,
            priority=int(slot.priority),
            is_filled=slot.is_filled,
            next_strategy_ids=list(slot.next_strategy_ids),
            queue_name=slot.queue_name,
            rate_limit_key=slot.rate_limit_key,
            rate_limit_units=slot.rate_limit_units,
            acquired_at=slot.acquired_at,
            created_at=slot.created_at,
        )

    @staticmethod
    def _update_record_from_domain(
        record: WorkflowConcurrencySlotModel, slot: ConcurrencySlot
    ) -> None:
        record.is_filled = slot.is_filled
        record.acquired_at = slot.acquired_at
        record.next_strategy_ids = list(slot.next_strategy_ids)

    @staticmethod
    def _to_domain_model(
        record: WorkflowConcurrencySlotModel,
    ) -> ConcurrencySlot:
        return ConcurrencySlot(
            sort_id=record.sort_id,
            tenant_id=record.tenant_id,
            strategy_id=record.strategy_id,
            concurrency_key=record.concurrency_key,
            run_id=record.run_id,
            step_run_id=record.step_run_id,
            step_created_at=record.step_created_at,
            retry_count=record.retry_count,
            priority=Priority(record.priority),
            is_filled=record.is_filled,
            next_strategy_ids=tuple(record.next_strategy_ids),
            queue_name=record.queue_name,
            rate_limit_key=record.rate_limit_key,
            rate_limit_units=record.rate_limit_units,
            acquired_at=record.acquired_at,
            created_at=record.created_at,
        )


class SqlAlchemyWorkflowRateLimitRepository(BaseSqlAlchemyRepository, WorkflowRateLimitPort):
    """SQLAlchemy adapter for token-bucket rate limit state."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

    async def get_or_create_bucket(
        self,
        *,
        tenant_id: str,
        rate_limit_key: str,
        capacity: int,
        refill_per_second: float,
        now: datetime,
    ) -> RateLimitBucket:
        stmt = select(WorkflowRateLimitBucketModel).where(
            WorkflowRateLimitBucketModel.tenant_id == tenant_id,
            WorkflowRateLimitBucketModel.rate_limit_key == rate_limit_key,
        )
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        if record is not None:
            return self._to_domain_model(record)

        bucket = RateLimitBucket(
            tenant_id=tenant_id,
            rate_limit_key=rate_limit_key,
            capacity=capacity,
            refill_per_second=refill_per_second,
            tokens=float(capacity),
            refilled_at=now,
        )
        self._session.add(self._to_orm_model(bucket))
        await self._session.flush()
        return bucket

    async def save_bucket(self, bucket: RateLimitBucket) -> None:
        stmt = select(WorkflowRateLimitBucketModel).where(
            WorkflowRateLimitBucketModel.tenant_id == bucket.tenant_id,
            WorkflowRateLimitBucketModel.rate_limit_key == bucket.rate_limit_key,
        )
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        if record is None:
            self._session.add(self._to_orm_model(bucket))
        else:
            self._update_record_from_domain(record, bucket)

    @staticmethod
    def _to_orm_model(bucket: RateLimitBucket) -> WorkflowRateLimitBucketModel:
        return WorkflowRateLimitBucketModel(
            tenant_id=bucket.tenant_id,
            rate_limit_key=bucket.rate_limit_key,
            capacity=bucket.capacity,
            refill_per_second=bucket.refill_per_second,
            tokens=bucket.tokens,
            refilled_at=bucket.refilled_at,
            paused_at=bucket.paused_at,
            paused_until=bucket.paused_until,
        )

    @staticmethod
    def _update_record_from_domain(
        record: WorkflowRateLimitBucketModel, bucket: RateLimitBucket
    ) -> None:
        record.capacity = bucket.capacity
        record.refill_per_second = bucket.refill_per_second
        record.tokens = bucket.tokens
        record.refilled_at = bucket.refilled_at
        record.paused_at = bucket.paused_at
        record.paused_until = bucket.paused_until

    @staticmethod
    def _to_domain_model(record: WorkflowRateLimitBucketModel) -> RateLimitBucket:
        return RateLimitBucket(
            tenant_id=record.tenant_id,
            rate_limit_key=record.rate_limit_key,
            capacity=record.capacity,
            refill_per_second=record.refill_per_second,
            tokens=record.tokens,
            refilled_at=record.refilled_at,
            paused_at=record.paused_at,
            paused_until=record.paused_until,
        )


class SqlAlchemyWorkflowPayloadStoreRepository(BaseSqlAlchemyRepository, WorkflowPayloadStorePort):
    """SQLAlchemy adapter for decoupled payloads (`workflow_payloads`) with zero-copy reference resolution."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

    async def save_payload(self, record: PayloadRecord) -> None:
        stmt = select(WorkflowPayloadModel).where(
            WorkflowPayloadModel.tenant_id == record.tenant_id,
            WorkflowPayloadModel.owner_id == record.owner_id,
            WorkflowPayloadModel.payload_type == record.payload_type.value,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            self._session.add(self._to_orm_model(record))
        else:
            self._update_record_from_domain(existing, record)

    async def get_payload(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        payload_type: PayloadType,
    ) -> PayloadRecord | None:
        stmt = select(WorkflowPayloadModel).where(
            WorkflowPayloadModel.tenant_id == tenant_id,
            WorkflowPayloadModel.owner_id == owner_id,
            WorkflowPayloadModel.payload_type == payload_type.value,
        )
        rec = (await self._session.execute(stmt)).scalar_one_or_none()
        if rec is None:
            return None
        return self._to_domain_model(rec)

    async def resolve_step_input(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
    ) -> JsonDict:
        rec = await self.get_payload(
            tenant_id=tenant_id,
            owner_id=step_run_id,
            payload_type=PayloadType.STEP_INPUT,
        )
        if rec is None:
            return {}
        if rec.location == PayloadLocation.INLINE and rec.inline_content is not None:
            return dict(rec.inline_content)
        if (
            rec.location == PayloadLocation.REFERENCE
            and rec.payload_reference_id is not None
        ):
            ref_rec = await self.get_payload(
                tenant_id=tenant_id,
                owner_id=rec.payload_reference_id,
                payload_type=PayloadType.RUN_INPUT,
            )
            if ref_rec is not None and ref_rec.inline_content is not None:
                return dict(ref_rec.inline_content)
        return {}

    @staticmethod
    def _to_orm_model(record: PayloadRecord) -> WorkflowPayloadModel:
        return WorkflowPayloadModel(
            tenant_id=record.tenant_id,
            owner_id=record.owner_id,
            owner_created_at=record.owner_created_at,
            payload_type=record.payload_type.value,
            location=record.location.value,
            inline_content=(
                dict(record.inline_content)
                if record.inline_content is not None
                else None
            ),
            external_ref=record.external_ref,
            payload_reference_id=record.payload_reference_id,
            payload_reference_created_at=record.payload_reference_created_at,
            size_bytes=record.size_bytes,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _update_record_from_domain(
        orm_record: WorkflowPayloadModel, record: PayloadRecord
    ) -> None:
        orm_record.location = record.location.value
        orm_record.inline_content = (
            dict(record.inline_content)
            if record.inline_content is not None
            else None
        )
        orm_record.external_ref = record.external_ref
        orm_record.payload_reference_id = record.payload_reference_id
        orm_record.payload_reference_created_at = record.payload_reference_created_at
        orm_record.size_bytes = record.size_bytes
        orm_record.updated_at = record.updated_at

    @staticmethod
    def _to_domain_model(record: WorkflowPayloadModel) -> PayloadRecord:
        return PayloadRecord(
            tenant_id=record.tenant_id,
            owner_id=record.owner_id,
            owner_created_at=record.owner_created_at,
            payload_type=PayloadType(record.payload_type),
            location=PayloadLocation(record.location),
            inline_content=(
                dict(record.inline_content)
                if record.inline_content is not None
                else None
            ),
            external_ref=record.external_ref,
            payload_reference_id=record.payload_reference_id,
            payload_reference_created_at=record.payload_reference_created_at,
            size_bytes=record.size_bytes,
            updated_at=record.updated_at,
        )


class SqlAlchemyWorkflowIdempotencyRepository(BaseSqlAlchemyRepository, WorkflowIdempotencyPort):
    """SQLAlchemy adapter for cross-partition idempotency claims (`workflow_idempotency_keys`)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

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
        stmt = select(WorkflowIdempotencyKeyModel).where(
            WorkflowIdempotencyKeyModel.tenant_id == tenant_id,
            WorkflowIdempotencyKeyModel.workflow_id == workflow_id,
            WorkflowIdempotencyKeyModel.key == key,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None and existing.expires_at > now:
            return Result.err(
                DuplicateIdempotencyKeyError.for_key(
                    workflow_id=workflow_id,
                    idempotency_key=key,
                    existing_run_id=existing.claimed_by_run_id,
                )
            )

        domain_rec = IdempotencyKeyRecord(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            key=key,
            claimed_by_run_id=run_id,
            eviction_policy=eviction_policy,
            expires_at=now + ttl,
            updated_at=now,
        )
        if existing is None:
            self._session.add(self._to_orm_model(domain_rec))
        else:
            self._update_record_from_domain(existing, domain_rec)
        return Result.ok(domain_rec)

    async def release_on_terminal_status(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        run_id: str,
    ) -> None:
        await self._session.execute(
            delete(WorkflowIdempotencyKeyModel).where(
                WorkflowIdempotencyKeyModel.tenant_id == tenant_id,
                WorkflowIdempotencyKeyModel.workflow_id == workflow_id,
                WorkflowIdempotencyKeyModel.claimed_by_run_id == run_id,
                WorkflowIdempotencyKeyModel.eviction_policy
                == IdempotencyEvictionPolicy.ON_TERMINAL_STATUS.value,
            )
        )

    @staticmethod
    def _to_orm_model(
        record: IdempotencyKeyRecord,
    ) -> WorkflowIdempotencyKeyModel:
        return WorkflowIdempotencyKeyModel(
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            key=record.key,
            claimed_by_run_id=record.claimed_by_run_id,
            eviction_policy=record.eviction_policy.value,
            expires_at=record.expires_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _update_record_from_domain(
        orm_record: WorkflowIdempotencyKeyModel, record: IdempotencyKeyRecord
    ) -> None:
        orm_record.claimed_by_run_id = record.claimed_by_run_id
        orm_record.eviction_policy = record.eviction_policy.value
        orm_record.expires_at = record.expires_at
        orm_record.updated_at = record.updated_at

    @staticmethod
    def _to_domain_model(
        record: WorkflowIdempotencyKeyModel,
    ) -> IdempotencyKeyRecord:
        return IdempotencyKeyRecord(
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            key=record.key,
            claimed_by_run_id=record.claimed_by_run_id,
            eviction_policy=IdempotencyEvictionPolicy(record.eviction_policy),
            expires_at=record.expires_at,
            updated_at=record.updated_at,
        )


__all__ = [
    "SqlAlchemyWorkflowConcurrencyRepository",
    "SqlAlchemyWorkflowIdempotencyRepository",
    "SqlAlchemyWorkflowMatchRepository",
    "SqlAlchemyWorkflowPayloadStoreRepository",
    "SqlAlchemyWorkflowQueueRepository",
    "SqlAlchemyWorkflowRateLimitRepository",
    "SqlAlchemyWorkflowRunRepository",
]
