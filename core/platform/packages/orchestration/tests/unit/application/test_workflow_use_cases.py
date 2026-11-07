"""Hexagonal application tests for all Durable Workflow Engine Use Cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from seedwork.domain.types import JsonDict

from orchestration.application.default_error_policy import DefaultStepErrorPolicy
from orchestration.application.services import (
    InMemoryPredicateRegistry,
    InMemoryStepHandlerRegistry,
    InMemoryWorkflowDefinitionRegistry,
    WorkflowStepSchedulerService,
)
from orchestration.application.use_cases import (
    CancelRunCommand,
    CancelRunUseCase,
    ClaimStepsCommand,
    ClaimStepsUseCase,
    CompleteStepCommand,
    CompleteStepUseCase,
    FailStepCommand,
    FailStepUseCase,
    ReapExpiredLeasesCommand,
    ReapExpiredLeasesUseCase,
    ReplayFailedStepCommand,
    ReplayFailedStepUseCase,
    ResolveMatchConditionsCommand,
    ResolveMatchConditionsUseCase,
    SkipFailedStepCommand,
    SkipFailedStepUseCase,
    StartRunCommand,
    StartRunUseCase,
)
from orchestration.domain.constants import (
    ConcurrencyStrategy,
    ConditionKind,
    EffectPolicy,
    ErrorDecisionKind,
    IdempotencyEvictionPolicy,
    NodeKind,
    RunStatus,
    StepFailureCode,
    StepStatus,
    WorkflowErrorCode,
)
from orchestration.domain.definition import (
    ConcurrencyPolicy,
    NodeDefinition,
    RateLimitPolicy,
    RepeatUntilSpec,
    RetryPolicy,
    WaitEventSpec,
    WorkflowDefinition,
)
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import ReconcileOutcome, RetryableFailure, StepFailure
from orchestration.ports.inbound.step_handler_port import (
    ReconcilableStepHandlerPort,
    StepContext,
)
from orchestration.testing import InMemoryWorkflowUnitOfWork


class _EngineHarness:
    """Self-contained hexagonal test harness wiring all workflow use cases over InMemoryWorkflowUnitOfWork."""

    def __init__(self) -> None:
        self.uow = InMemoryWorkflowUnitOfWork()
        self.definitions = InMemoryWorkflowDefinitionRegistry()
        self.handlers = InMemoryStepHandlerRegistry()
        self.predicates = InMemoryPredicateRegistry()
        self.scheduler = WorkflowStepSchedulerService()
        self.error_policy = DefaultStepErrorPolicy()

        self.match_resolver = ResolveMatchConditionsUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            step_scheduler=self.scheduler,
            predicate_evaluator=self.predicates,
        )
        self.start_run = StartRunUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            step_scheduler=self.scheduler,
        )
        self.claim_steps = ClaimStepsUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            step_scheduler=self.scheduler,
            match_resolver=self.match_resolver,
        )
        self.complete_step = CompleteStepUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            step_scheduler=self.scheduler,
            match_resolver=self.match_resolver,
            predicate_evaluator=self.predicates,
        )
        self.fail_step = FailStepUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            error_policy=self.error_policy,
            step_scheduler=self.scheduler,
            match_resolver=self.match_resolver,
        )
        self.reap_leases = ReapExpiredLeasesUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            fail_step_use_case=self.fail_step,
            complete_step_use_case=self.complete_step,
            handler_registry=self.handlers,
        )
        self.cancel_run = CancelRunUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            step_scheduler=self.scheduler,
        )
        self.replay_step = ReplayFailedStepUseCase(
            uow_factory=lambda: self.uow,
            definition_registry=self.definitions,
            step_scheduler=self.scheduler,
        )
        self.skip_step = SkipFailedStepUseCase(
            uow_factory=lambda: self.uow,
            match_resolver=self.match_resolver,
        )


async def test_end_to_end_dag_execution_with_zero_copy_payload_and_idempotency_release() -> None:
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    defn = WorkflowDefinition(
        workflow_id="energy.meter_disconnect",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="validate_account",
                kind=NodeKind.TASK,
                step_type="stitch.validate",
            ),
            NodeDefinition(
                node_key="wait_disconnect_ack",
                kind=NodeKind.WAIT_FOR_EVENT,
                parents=("validate_account",),
                wait_event=WaitEventSpec(
                    event_key="canonical.meter_ack",
                    resource_hint_template="mtr_500",
                    timeout=timedelta(minutes=30),
                ),
            ),
            NodeDefinition(
                node_key="finalize_billing",
                kind=NodeKind.TASK,
                step_type="stitch.billing",
                parents=("wait_disconnect_ack",),
            ),
        ),
    )
    assert harness.definitions.register(defn).is_ok

    # 1. Start run with ON_TERMINAL_STATUS idempotency policy
    start_res = await harness.start_run.execute(
        StartRunCommand(
            tenant_id="ten_energy",
            workflow_id="energy.meter_disconnect",
            workflow_version=1,
            idempotency_key="disc_mtr_500",
            input_payload={"meter_id": "mtr_500", "requested_by": "op_1"},
            trace_id="trc_100",
            idempotency_eviction_policy=IdempotencyEvictionPolicy.ON_TERMINAL_STATUS,
            now=now,
        )
    )
    assert start_res.is_ok
    run_id = start_res.unwrap().run_id

    # Duplicate idempotency key is rejected while run is active
    dup_res = await harness.start_run.execute(
        StartRunCommand(
            tenant_id="ten_energy",
            workflow_id="energy.meter_disconnect",
            workflow_version=1,
            idempotency_key="disc_mtr_500",
            input_payload={"meter_id": "mtr_500"},
            trace_id="trc_101",
            now=now,
        )
    )
    assert dup_res.is_err
    assert dup_res.unwrap_err().code == WorkflowErrorCode.DUPLICATE_IDEMPOTENCY_KEY

    # 2. Claim root step `validate_account` and verify zero-copy RUN_INPUT payload resolution
    claim1 = await harness.claim_steps.execute(ClaimStepsCommand(worker_id="wrk_1", now=now))
    assert claim1.is_ok
    claimed_root = claim1.unwrap().claimed_steps[0]
    assert claimed_root.context.node_key == "validate_account"
    assert claimed_root.input_payload == {
        "meter_id": "mtr_500",
        "requested_by": "op_1",
    }

    # 3. Complete `validate_account` -> triggers two-stage CREATE_MATCH on `wait_disconnect_ack` (status WAITING)
    comp1 = await harness.complete_step.execute(
        CompleteStepCommand(
            tenant_id="ten_energy",
            run_id=run_id,
            node_key="validate_account",
            fencing_retry_count=0,
            worker_id="wrk_1",
            attempt_id=claimed_root.attempt_id,
            output_payload={"account_valid": True},
            now=now + timedelta(seconds=5),
        )
    )
    assert comp1.is_ok
    assert comp1.unwrap().run_status == RunStatus.WAITING

    # 4. External canonical event arrives -> satisfies stage-2 SIGNAL_WAIT match on `wait_disconnect_ack`
    # and automatically queues `finalize_billing`!
    sig_res = await harness.match_resolver.execute(
        ResolveMatchConditionsCommand(
            tenant_id="ten_energy",
            condition_kind=ConditionKind.CANONICAL_EVENT,
            event_key="canonical.meter_ack",
            resource_hint="mtr_500",
            payload={"relay_state": "OPEN"},
            now=now + timedelta(seconds=20),
        )
    )
    assert sig_res.is_ok
    assert len(sig_res.unwrap().queued_step_ids) == 1

    # 5. Claim and complete `finalize_billing`
    claim2 = await harness.claim_steps.execute(
        ClaimStepsCommand(worker_id="wrk_1", now=now + timedelta(seconds=21))
    )
    assert claim2.is_ok
    claimed_final = claim2.unwrap().claimed_steps[0]
    assert claimed_final.context.node_key == "finalize_billing"

    comp2 = await harness.complete_step.execute(
        CompleteStepCommand(
            tenant_id="ten_energy",
            run_id=run_id,
            node_key="finalize_billing",
            fencing_retry_count=0,
            worker_id="wrk_1",
            attempt_id=claimed_final.attempt_id,
            output_payload={"billed": True},
            now=now + timedelta(seconds=25),
        )
    )
    assert comp2.is_ok
    assert comp2.unwrap().run_status == RunStatus.SUCCEEDED

    # 6. Because idempotency policy was ON_TERMINAL_STATUS, starting a new run with the same key now succeeds!
    re_start = await harness.start_run.execute(
        StartRunCommand(
            tenant_id="ten_energy",
            workflow_id="energy.meter_disconnect",
            workflow_version=1,
            idempotency_key="disc_mtr_500",
            input_payload={"meter_id": "mtr_500"},
            trace_id="trc_102",
            now=now + timedelta(seconds=30),
        )
    )
    assert re_start.is_ok


async def test_429_rate_limit_parking_releases_concurrency_slot_and_preserves_app_retry_count() -> (
    None
):
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    defn = WorkflowDefinition(
        workflow_id="energy.itron_sync",
        version=1,
        workflow_concurrency=ConcurrencyPolicy(
            strategy_id="strategy.serial_tenant",
            strategy=ConcurrencyStrategy.SERIAL,
            max_runs=1,
            key_template="itron_conn_1",
        ),
        nodes=(
            NodeDefinition(
                node_key="push_reads",
                kind=NodeKind.TASK,
                step_type="stitch.push",
                retry_policy=RetryPolicy(max_attempts=2),
                rate_limit_policy=RateLimitPolicy(
                    rate_limit_key="itron_conn_1",
                    units=1,
                    capacity=10,
                    refill_per_second=1.0,
                ),
            ),
        ),
    )
    assert harness.definitions.register(defn).is_ok

    # Start Run 1 and Run 2 on the same concurrency key (max_runs=1 -> Run 1 queues, Run 2 waits in concurrency slot)
    r1 = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.itron_sync",
                workflow_version=1,
                idempotency_key="sync_1",
                input_payload={"batch": 1},
                concurrency_key="itron_conn_1",
                trace_id="t1",
                now=now,
            )
        )
    ).unwrap()
    r2 = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.itron_sync",
                workflow_version=1,
                idempotency_key="sync_2",
                input_payload={"batch": 2},
                concurrency_key="itron_conn_1",
                trace_id="t2",
                now=now,
            )
        )
    ).unwrap()

    # Claim Run 1's step
    claimed_batch = (
        await harness.claim_steps.execute(ClaimStepsCommand(worker_id="wrk_1", now=now))
    ).unwrap()
    assert len(claimed_batch.claimed_steps) == 1
    assert claimed_batch.claimed_steps[0].context.run_id == r1.run_id

    # Run 1 receives 429 RATE_LIMITED with Retry-After=60s ->
    # Parks Run 1 in paused_items, preserves app_retry_count == 0, AND releases concurrency slot so Run 2 is promoted!
    fail_res = await harness.fail_step.execute(
        FailStepCommand(
            tenant_id="ten_1",
            run_id=r1.run_id,
            node_key="push_reads",
            fencing_retry_count=0,
            worker_id="wrk_1",
            attempt_id=claimed_batch.claimed_steps[0].attempt_id,
            failure=RetryableFailure(
                code=StepFailureCode.RATE_LIMITED,
                detail="HTTP 429 Retry-After: 60",
                retry_after=timedelta(seconds=60),
            ),
            now=now,
        )
    )
    assert fail_res.is_ok
    dto = fail_res.unwrap()
    assert dto.decision == ErrorDecisionKind.PARK_FOR_RATE_LIMIT
    assert dto.app_retry_count == 0
    assert dto.retry_count == 0
    assert len(harness.uow.queue.paused_items) >= 1

    # When 60s pause expires at now + 61s, unpausing re-schedules Run 1 and Run 2!
    claim_after_pause = (
        await harness.claim_steps.execute(
            ClaimStepsCommand(worker_id="wrk_1", now=now + timedelta(seconds=61))
        )
    ).unwrap()
    assert len(claim_after_pause.claimed_steps) == 1
    assert claim_after_pause.claimed_steps[0].context.run_id in (r1.run_id, r2.run_id)


async def test_lease_expiry_on_operator_gated_effect_halts_and_allows_operator_skip() -> None:
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    defn = WorkflowDefinition(
        workflow_id="energy.grid_switch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="open_breaker",
                kind=NodeKind.TASK,
                step_type="stitch.breaker",
                effect_policy=EffectPolicy.OPERATOR_GATED_EFFECT,
            ),
            NodeDefinition(
                node_key="notify_scada",
                kind=NodeKind.TASK,
                step_type="stitch.notify",
                parents=("open_breaker",),
            ),
        ),
    )
    assert harness.definitions.register(defn).is_ok

    run_dto = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.grid_switch",
                workflow_version=1,
                idempotency_key="sw_1",
                input_payload={},
                trace_id="t1",
                now=now,
            )
        )
    ).unwrap()

    claimed = (
        await harness.claim_steps.execute(
            ClaimStepsCommand(
                worker_id="wrk_1",
                lease_ttl=timedelta(seconds=30),
                now=now,
            )
        )
    ).unwrap()
    assert len(claimed.claimed_steps) == 1

    # Simulate worker crash: at now + 35s lease is expired -> ReapExpiredLeasesUseCase halts step with AMBIGUOUS_EFFECT!
    reap_res = (
        await harness.reap_leases.execute(ReapExpiredLeasesCommand(now=now + timedelta(seconds=35)))
    ).unwrap()
    assert len(reap_res.reaped_lease_step_ids) == 1

    run_state = (await harness.uow.runs.get_by_id("ten_1", run_dto.run_id)).unwrap()
    assert run_state.status == RunStatus.FAILED
    assert run_state.steps["open_breaker"].failure_code == StepFailureCode.AMBIGUOUS_EFFECT.value

    # Operator verifies breaker opened in SCADA and invokes SkipFailedStepUseCase with manual output!
    skip_res = await harness.skip_step.execute(
        SkipFailedStepCommand(
            tenant_id="ten_1",
            run_id=run_dto.run_id,
            node_key="open_breaker",
            manual_output={"verified_by": "engineer_jane"},
            reason="Verified breaker open in SCADA telemetry.",
            now=now + timedelta(seconds=60),
        )
    )
    assert skip_res.is_ok
    assert len(skip_res.unwrap().queued_child_step_ids) == 1


async def test_branch_and_repeat_until_control_nodes() -> None:
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    poll_counter = {"count": 0}

    def check_export_done(payload: JsonDict) -> bool:
        return payload.get("ready") is True

    def check_high_voltage(payload: JsonDict) -> bool:
        parents = payload.get("parents")
        if isinstance(parents, dict):
            poll_out = parents.get("poll_job")
            if isinstance(poll_out, dict):
                return poll_out.get("voltage") == "HIGH"
        return False

    harness.predicates.register("pred.export_done", check_export_done)
    harness.predicates.register("pred.high_voltage", check_high_voltage)

    defn = WorkflowDefinition(
        workflow_id="energy.export_and_branch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="poll_job",
                kind=NodeKind.REPEAT_UNTIL,
                step_type="stitch.poll",
                repeat_until=RepeatUntilSpec(
                    predicate_id="pred.export_done",
                    interval=timedelta(seconds=5),
                    max_iterations=3,
                ),
            ),
            NodeDefinition(
                node_key="voltage_branch",
                kind=NodeKind.BRANCH,
                parents=("poll_job",),
                branch_predicate_id="pred.high_voltage",
            ),
            NodeDefinition(
                node_key="hv_handler",
                kind=NodeKind.TASK,
                step_type="stitch.hv",
                parents=("voltage_branch",),
            ),
        ),
    )
    assert harness.definitions.register(defn).is_ok

    run_dto = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.export_and_branch",
                workflow_version=1,
                idempotency_key="exp_1",
                input_payload={},
                trace_id="t1",
                now=now,
            )
        )
    ).unwrap()

    # Attempt 1 of poll_job returns {"ready": False} -> REPEAT_UNTIL re-schedules after 5s!
    c1 = (
        (await harness.claim_steps.execute(ClaimStepsCommand(worker_id="wrk_1", now=now)))
        .unwrap()
        .claimed_steps[0]
    )
    comp1 = (
        await harness.complete_step.execute(
            CompleteStepCommand(
                tenant_id="ten_1",
                run_id=run_dto.run_id,
                node_key="poll_job",
                fencing_retry_count=c1.context.retry_count,
                worker_id="wrk_1",
                attempt_id=c1.attempt_id,
                output_payload={"ready": False},
                now=now + timedelta(seconds=1),
            )
        )
    ).unwrap()
    assert comp1.step_status == StepStatus.READY
    assert comp1.queued_child_step_ids == ()

    # Attempt 2 at now + 6s returns {"ready": True, "voltage": "LOW"} ->
    # poll_job completes, voltage_branch evaluates False -> skips voltage_branch AND cascades SKIP to hv_handler -> run SUCCEEDED!
    c2 = (
        (
            await harness.claim_steps.execute(
                ClaimStepsCommand(worker_id="wrk_1", now=now + timedelta(seconds=6))
            )
        )
        .unwrap()
        .claimed_steps[0]
    )
    assert c2.context.retry_count == 1
    poll_counter["count"] += 1

    comp2 = (
        await harness.complete_step.execute(
            CompleteStepCommand(
                tenant_id="ten_1",
                run_id=run_dto.run_id,
                node_key="poll_job",
                fencing_retry_count=c2.context.retry_count,
                worker_id="wrk_1",
                attempt_id=c2.attempt_id,
                output_payload={"ready": True, "voltage": "LOW"},
                now=now + timedelta(seconds=7),
            )
        )
    ).unwrap()
    assert comp2.run_status == RunStatus.SUCCEEDED
    final_run = (await harness.uow.runs.get_by_id("ten_1", run_dto.run_id)).unwrap()
    assert final_run.steps["voltage_branch"].status == StepStatus.SKIPPED
    assert final_run.steps["hv_handler"].status == StepStatus.SKIPPED


async def test_operator_cancel_and_replay_actions() -> None:
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    defn = WorkflowDefinition(
        workflow_id="energy.simple",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="only_step",
                kind=NodeKind.TASK,
                step_type="stitch.only",
                retry_policy=RetryPolicy(max_attempts=1),
            ),
        ),
    )
    assert harness.definitions.register(defn).is_ok

    r1 = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.simple",
                workflow_version=1,
                idempotency_key="op_1",
                input_payload={},
                trace_id="t1",
                now=now,
            )
        )
    ).unwrap()

    # Claim and fail terminally (max_attempts=1)
    c1 = (
        (await harness.claim_steps.execute(ClaimStepsCommand(worker_id="wrk_1", now=now)))
        .unwrap()
        .claimed_steps[0]
    )
    fail_dto = (
        await harness.fail_step.execute(
            FailStepCommand(
                tenant_id="ten_1",
                run_id=r1.run_id,
                node_key="only_step",
                fencing_retry_count=0,
                worker_id="wrk_1",
                attempt_id=c1.attempt_id,
                failure=RetryableFailure(
                    code=StepFailureCode.UPSTREAM_5XX,
                    detail="502 Bad Gateway",
                ),
                now=now,
            )
        )
    ).unwrap()
    assert fail_dto.run_status == RunStatus.FAILED

    # Replay failed step -> increments retry_count to 1, resets app_retry_count to 0, re-queues step
    replay_dto = (
        await harness.replay_step.execute(
            ReplayFailedStepCommand(
                tenant_id="ten_1",
                run_id=r1.run_id,
                node_key="only_step",
                now=now + timedelta(seconds=10),
            )
        )
    ).unwrap()
    assert replay_dto.retry_count == 1
    assert replay_dto.app_retry_count == 0
    assert replay_dto.run_status == RunStatus.QUEUED

    # Cancel run
    cancel_dto = (
        await harness.cancel_run.execute(
            CancelRunCommand(
                tenant_id="ten_1",
                run_id=r1.run_id,
                reason="Cancelled by operator.",
                now=now + timedelta(seconds=15),
            )
        )
    ).unwrap()
    assert cancel_dto.status == RunStatus.CANCELLED


class _ReconcilableInvoiceHandler(ReconcilableStepHandlerPort[JsonDict, JsonDict]):
    @property
    def step_type(self) -> str:
        return "stitch.create_invoice"

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.RECONCILABLE_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        return Result.ok({"invoice_id": "inv_100"})

    async def reconcile(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[ReconcileOutcome[JsonDict], StepFailure]:
        return Result.ok(ReconcileOutcome.adopt({"invoice_id": "inv_reconciled_100"}))


async def test_reap_expired_leases_reconciles_external_effect_and_completes_step() -> None:
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    harness.handlers.register(_ReconcilableInvoiceHandler())

    defn = WorkflowDefinition(
        workflow_id="energy.reconcilable_invoice",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="create_invoice",
                kind=NodeKind.TASK,
                step_type="stitch.create_invoice",
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
            NodeDefinition(
                node_key="archive_invoice",
                kind=NodeKind.TASK,
                step_type="stitch.archive",
                parents=("create_invoice",),
            ),
        ),
    )
    assert harness.definitions.register(defn).is_ok

    started = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.reconcilable_invoice",
                workflow_version=1,
                idempotency_key="idem_rec_1",
                input_payload={"account_id": "acc_1"},
                trace_id="trc_rec_1",
                now=now,
            )
        )
    ).unwrap()

    claimed = (
        await harness.claim_steps.execute(
            ClaimStepsCommand(
                worker_id="wrk_1",
                lease_ttl=timedelta(seconds=30),
                now=now,
            )
        )
    ).unwrap()
    assert len(claimed.claimed_steps) == 1

    # Lease expires after 31s; reaper reconciles external side effect and completes `create_invoice` -> queues `archive_invoice`!
    reap_res = (
        await harness.reap_leases.execute(ReapExpiredLeasesCommand(now=now + timedelta(seconds=31)))
    ).unwrap()
    assert len(reap_res.reconciled_step_ids) == 1

    run = (await harness.uow.runs.get_by_id("ten_1", started.run_id)).unwrap()
    assert run.steps["create_invoice"].status == StepStatus.SUCCEEDED
    assert run.steps["archive_invoice"].status == StepStatus.READY
    assert len(harness.uow.runs.drained_events) > 0


async def test_blocked_version_unavailable_run_restores_when_definition_becomes_available() -> None:
    harness = _EngineHarness()
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    defn_v2 = WorkflowDefinition(
        workflow_id="energy.dynamic_version",
        version=2,
        nodes=(
            NodeDefinition(
                node_key="step_v2",
                kind=NodeKind.TASK,
                step_type="stitch.calc",
            ),
        ),
    )
    assert harness.definitions.register(defn_v2).is_ok
    started = (
        await harness.start_run.execute(
            StartRunCommand(
                tenant_id="ten_1",
                workflow_id="energy.dynamic_version",
                workflow_version=2,
                idempotency_key="idem_dyn_1",
                input_payload={"val": 42},
                trace_id="trc_dyn_1",
                now=now,
            )
        )
    ).unwrap()

    # Temporarily remove definition to simulate missing worker version
    del harness.definitions._definitions[("energy.dynamic_version", 2)]

    claimed_empty = (
        await harness.claim_steps.execute(
            ClaimStepsCommand(
                worker_id="wrk_1",
                now=now,
            )
        )
    ).unwrap()
    assert len(claimed_empty.claimed_steps) == 0

    run_blocked = (await harness.uow.runs.get_by_id("ten_1", started.run_id)).unwrap()
    assert run_blocked.status == RunStatus.BLOCKED_VERSION_UNAVAILABLE

    # Definition becomes available
    assert harness.definitions.register(defn_v2).is_ok

    # Claim again after 5-minute delayed retry window
    claimed_restored = (
        await harness.claim_steps.execute(
            ClaimStepsCommand(
                worker_id="wrk_1",
                now=now + timedelta(minutes=6),
            )
        )
    ).unwrap()
    assert len(claimed_restored.claimed_steps) == 1

    run_restored = (await harness.uow.runs.get_by_id("ten_1", started.run_id)).unwrap()
    assert run_restored.status == RunStatus.RUNNING
