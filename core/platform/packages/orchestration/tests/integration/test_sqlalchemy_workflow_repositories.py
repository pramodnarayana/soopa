"""Narrow PostgreSQL SAVEPOINT integration tests for SqlAlchemyWorkflowUnitOfWork and all 7 repositories."""

from __future__ import annotations

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
    started = (
        await start_run.execute(
            StartRunCommand(
                tenant_id="ten_pg_01",
                workflow_id="energy.pg_integration_stitch",
                workflow_version=1,
                input_payload={"meter_id": "mtr_pg_100", "kwh": 99.5},
                trace_id="trc_pg_01",
                idempotency_key="idem_pg_100",
                idempotency_eviction_policy=IdempotencyEvictionPolicy.ON_TERMINAL_STATUS,
                concurrency_key="mtr_pg_100",
                now=now,
            )
        )
    ).unwrap()
    assert not started.was_deduplicated

    persisted_run = (await uow.runs.get_by_id("ten_pg_01", started.run_id)).unwrap()
    root_step = persisted_run.get_step("ingest_ami").unwrap()
    step_in_rec = await uow.payloads.get_payload(
        tenant_id="ten_pg_01",
        owner_id=root_step.id,
        payload_type=PayloadType.STEP_INPUT,
    )
    assert step_in_rec is not None
    assert step_in_rec.location == PayloadLocation.REFERENCE

    # 2. Claim root step, then report 429 rate-limit failure -> parks in paused queue without burning app_retry_count
    claimed1 = (
        await claim_steps.execute(ClaimStepsCommand(worker_id="wrk_pg_1", now=now))
    ).unwrap()
    assert len(claimed1.claimed_steps) == 1
    assert claimed1.claimed_steps[0].input_payload == {
        "meter_id": "mtr_pg_100",
        "kwh": 99.5,
    }

    fail_429 = (
        await fail_step.execute(
            FailStepCommand(
                tenant_id="ten_pg_01",
                run_id=started.run_id,
                node_key="ingest_ami",
                fencing_retry_count=0,
                worker_id="wrk_pg_1",
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
        await claim_steps.execute(ClaimStepsCommand(worker_id="wrk_pg_1", now=t_unpause))
    ).unwrap()
    assert len(claimed2.claimed_steps) == 1
    assert claimed2.claimed_steps[0].context.retry_count == 0

    await complete_step.execute(
        CompleteStepCommand(
            tenant_id="ten_pg_01",
            run_id=started.run_id,
            node_key="ingest_ami",
            fencing_retry_count=0,
            worker_id="wrk_pg_1",
            attempt_id=claimed2.claimed_steps[0].attempt_id,
            output_payload={"normalized": True},
            now=t_unpause + timedelta(seconds=1),
        )
    )

    # 4. Claim and complete child step `emit_alert` -> run reaches SUCCEEDED
    t_child = t_unpause + timedelta(seconds=2)
    claimed3 = (
        await claim_steps.execute(ClaimStepsCommand(worker_id="wrk_pg_1", now=t_child))
    ).unwrap()
    assert len(claimed3.claimed_steps) == 1
    assert claimed3.claimed_steps[0].context.node_key == "emit_alert"

    done_res = (
        await complete_step.execute(
            CompleteStepCommand(
                tenant_id="ten_pg_01",
                run_id=started.run_id,
                node_key="emit_alert",
                fencing_retry_count=0,
                worker_id="wrk_pg_1",
                attempt_id=claimed3.claimed_steps[0].attempt_id,
                output_payload={"notified": True},
                now=t_child + timedelta(seconds=1),
            )
        )
    ).unwrap()
    assert done_res.run_status == RunStatus.SUCCEEDED
    assert done_res.step_status == StepStatus.SUCCEEDED
