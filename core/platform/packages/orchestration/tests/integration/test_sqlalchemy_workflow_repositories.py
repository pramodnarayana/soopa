"""Narrow PostgreSQL SAVEPOINT integration tests for SqlAlchemyWorkflowUnitOfWork and all 7 repositories."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.adapters.outbound.database import SqlAlchemyWorkflowUnitOfWork
from orchestration.application.default_error_policy import DefaultStepErrorPolicy
from orchestration.application.services import (
    InMemoryWorkflowDefinitionRegistry,
    WorkflowStepSchedulerService,
)
from orchestration.application.use_cases import (
    ClaimStepsCommand,
    ClaimStepsUseCase,
    CompleteStepCommand,
    CompleteStepUseCase,
    FailStepCommand,
    FailStepUseCase,
    ResolveMatchConditionsUseCase,
    StartRunCommand,
    StartRunUseCase,
)
from orchestration.domain.constants import (
    ConcurrencyStrategy,
    ErrorDecisionKind,
    IdempotencyEvictionPolicy,
    NodeKind,
    PayloadLocation,
    PayloadType,
    RunStatus,
    StepFailureCode,
    StepStatus,
)
from orchestration.domain.definition import (
    ConcurrencyPolicy,
    NodeDefinition,
    RateLimitPolicy,
    WorkflowDefinition,
)
from orchestration.domain.failures import RetryableFailure


async def test_postgres_savepoint_full_workflow_lifecycle_and_429_parking(
    workflow_session: AsyncSession,
) -> None:
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    uow = SqlAlchemyWorkflowUnitOfWork(workflow_session)
    definitions = InMemoryWorkflowDefinitionRegistry()
    scheduler = WorkflowStepSchedulerService()
    error_policy = DefaultStepErrorPolicy()

    defn = WorkflowDefinition(
        workflow_id="energy.pg_integration_stitch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="ingest_ami",
                kind=NodeKind.TASK,
                step_type="ip.stitch.ingest_ami",
                concurrency_policies=(
                    ConcurrencyPolicy(
                        strategy_id="strat_meter",
                        max_runs=1,
                        strategy=ConcurrencyStrategy.GROUP_ROUND_ROBIN,
                    ),
                ),
                rate_limit_policy=RateLimitPolicy(
                    rate_limit_key="itron_api",
                    units=1,
                    capacity=10,
                    refill_per_second=1.0,
                ),
            ),
            NodeDefinition(
                node_key="emit_alert",
                kind=NodeKind.TASK,
                step_type="ip.stitch.emit_notification",
                parents=("ingest_ami",),
            ),
        ),
    )
    assert definitions.register(defn).is_ok

    match_resolver = ResolveMatchConditionsUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=scheduler,
    )
    start_run = StartRunUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=scheduler,
    )
    claim_steps = ClaimStepsUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=scheduler,
        match_resolver=match_resolver,
    )
    complete_step = CompleteStepUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=scheduler,
        match_resolver=match_resolver,
    )
    fail_step = FailStepUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        error_policy=error_policy,
        step_scheduler=scheduler,
        match_resolver=match_resolver,
    )

    # 1. Start run with idempotency key and zero-copy root payload reference
    tenant_id = f"ten_{os.urandom(12).hex()}"
    first_trace_id = f"trc_{os.urandom(12).hex()}"
    first_idem_key = f"idem_{os.urandom(12).hex()}"
    worker_id = f"wrk_{os.urandom(12).hex()}"

    started = (
        await start_run.execute(
            StartRunCommand(
                tenant_id=tenant_id,
                workflow_id="energy.pg_integration_stitch",
                workflow_version=1,
                input_payload={"meter_id": "mtr_pg_100", "kwh": 99.5},
                trace_id=first_trace_id,
                idempotency_key=first_idem_key,
                idempotency_eviction_policy=IdempotencyEvictionPolicy.ON_TERMINAL_STATUS,
                concurrency_key="mtr_pg_100",
                now=now,
            )
        )
    ).unwrap()
    assert not started.was_deduplicated

    persisted_run = (await uow.runs.get_by_id(tenant_id, started.run_id)).unwrap()
    root_step = persisted_run.get_step("ingest_ami").unwrap()
    step_in_rec = await uow.payloads.get_payload(
        tenant_id=tenant_id,
        owner_id=root_step.id,
        payload_type=PayloadType.STEP_INPUT,
    )
    assert step_in_rec is not None
    assert step_in_rec.location == PayloadLocation.REFERENCE

    # 2. Claim root step, then report 429 rate-limit failure -> parks in paused queue without burning app_retry_count
    claimed1 = (await claim_steps.execute(ClaimStepsCommand(worker_id=worker_id, now=now))).unwrap()
    assert len(claimed1.claimed_steps) == 1
    assert claimed1.claimed_steps[0].input_payload == {
        "meter_id": "mtr_pg_100",
        "kwh": 99.5,
    }

    fail_429 = (
        await fail_step.execute(
            FailStepCommand(
                tenant_id=tenant_id,
                run_id=started.run_id,
                node_key="ingest_ami",
                fencing_retry_count=0,
                worker_id=worker_id,
                attempt_id=claimed1.claimed_steps[0].attempt_id,
                failure=RetryableFailure(
                    code=StepFailureCode.RATE_LIMITED,
                    detail="429 Too Many Requests",
                    retry_after=timedelta(seconds=30),
                ),
                now=now + timedelta(seconds=1),
            )
        )
    ).unwrap()
    assert fail_429.decision == ErrorDecisionKind.PARK_FOR_RATE_LIMIT
    assert fail_429.app_retry_count == 0
    assert fail_429.internal_retry_count == 0

    # 3. Advance clock past 30s -> unpauses and claims root step, then completes
    t_unpause = now + timedelta(seconds=35)
    claimed2 = (
        await claim_steps.execute(ClaimStepsCommand(worker_id=worker_id, now=t_unpause))
    ).unwrap()
    assert len(claimed2.claimed_steps) == 1
    assert claimed2.claimed_steps[0].context.retry_count == 0

    await complete_step.execute(
        CompleteStepCommand(
            tenant_id=tenant_id,
            run_id=started.run_id,
            node_key="ingest_ami",
            fencing_retry_count=0,
            worker_id=worker_id,
            attempt_id=claimed2.claimed_steps[0].attempt_id,
            output_payload={"normalized": True},
            now=t_unpause + timedelta(seconds=1),
        )
    )

    # 4. Claim and complete child step `emit_alert` -> run reaches SUCCEEDED
    t_child = t_unpause + timedelta(seconds=2)
    claimed3 = (
        await claim_steps.execute(ClaimStepsCommand(worker_id=worker_id, now=t_child))
    ).unwrap()
    assert len(claimed3.claimed_steps) == 1
    assert claimed3.claimed_steps[0].context.node_key == "emit_alert"

    done_res = (
        await complete_step.execute(
            CompleteStepCommand(
                tenant_id=tenant_id,
                run_id=started.run_id,
                node_key="emit_alert",
                fencing_retry_count=0,
                worker_id=worker_id,
                attempt_id=claimed3.claimed_steps[0].attempt_id,
                output_payload={"notified": True},
                now=t_child + timedelta(seconds=1),
            )
        )
    ).unwrap()
    assert done_res.run_status == RunStatus.SUCCEEDED
    assert done_res.step_status == StepStatus.SUCCEEDED

    # 5. Start a second run + another tenant's run and verify list_recent batch step hydration & filters
    second_trace_id = f"trc_{os.urandom(12).hex()}"
    started_second = (
        await start_run.execute(
            StartRunCommand(
                tenant_id=tenant_id,
                workflow_id="energy.pg_integration_stitch",
                workflow_version=1,
                input_payload={"meter_id": "mtr_pg_101", "kwh": 54.2},
                trace_id=second_trace_id,
                idempotency_key=f"idem_{os.urandom(12).hex()}",
                concurrency_key="mtr_pg_101",
                now=now + timedelta(minutes=2),
            )
        )
    ).unwrap()
    await start_run.execute(
        StartRunCommand(
            tenant_id=f"ten_{os.urandom(12).hex()}",
            workflow_id="energy.pg_integration_stitch",
            workflow_version=1,
            input_payload={"meter_id": "mtr_other", "kwh": 10.0},
            trace_id=f"trc_{os.urandom(12).hex()}",
            idempotency_key=f"idem_{os.urandom(12).hex()}",
            now=now + timedelta(minutes=3),
        )
    )

    recent_runs = await uow.runs.list_recent(tenant_id, limit=10)
    assert [r.id for r in recent_runs] == [started_second.run_id, started.run_id]
    assert set(recent_runs[0].steps.keys()) == {"ingest_ami", "emit_alert"}
    assert set(recent_runs[1].steps.keys()) == {"ingest_ami", "emit_alert"}

    succeeded_only = await uow.runs.list_recent(
        tenant_id,
        workflow_id="energy.pg_integration_stitch",
        status=RunStatus.SUCCEEDED,
        limit=10,
    )
    assert [r.id for r in succeeded_only] == [started.run_id]
    assert await uow.runs.list_recent(tenant_id, workflow_id="nonexistent.workflow") == ()
