"""Hexagonal unit tests for the IP Layer-4 Stitch Engine (canonical event triggers, signals, and worker ticks)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ip.engine.adapters.outbound.stitches import (
    EmitNotificationStepHandler,
    InMemoryStitchCatalogRegistry,
    NotificationOutboxPort,
    QueryReplicaStepHandler,
    ReplicaLookupPort,
)
from ip.engine.application.use_cases.stitch import (
    DispatchCanonicalEventToStitchesCommand,
    DispatchCanonicalEventToStitchesUseCase,
    ExecuteStitchWorkerTickCommand,
    ExecuteStitchWorkerTickUseCase,
)
from ip.engine.domain.enums import HttpWriteOperation, OutboundConflictStrategy
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.stitch import (
    EmitNotificationStepInput,
    ExecuteHttpActionStepInput,
    ExecuteHttpActionStepOutput,
    QueryReplicaStepInput,
    StitchStepType,
    StitchSubscription,
)
from notification.domain.constants import NotificationEventType
from orchestration.application.default_error_policy import DefaultStepErrorPolicy
from orchestration.application.services import (
    InMemoryStepHandlerRegistry,
    InMemoryWorkflowDefinitionRegistry,
    WorkflowStepSchedulerService,
)
from orchestration.application.use_cases import (
    ClaimStepsUseCase,
    CompleteStepUseCase,
    FailStepUseCase,
    ResolveMatchConditionsUseCase,
    StartRunUseCase,
)
from orchestration.domain.constants import EffectPolicy, NodeKind, RunStatus
from orchestration.domain.definition import (
    NodeDefinition,
    WaitEventSpec,
    WorkflowDefinition,
)
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from orchestration.testing import InMemoryWorkflowUnitOfWork
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope


class _FakeReplicaLookup(ReplicaLookupPort):
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], ReplicaRecord] = {}

    def add(self, record: ReplicaRecord) -> None:
        self.records[
            (
                record.tenant_id,
                record.connection_id,
                record.stream,
                record.record_key,
            )
        ] = record

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        return self.records.get((tenant_id, connection_id, stream, record_key))


class _FakeNotificationOutbox(NotificationOutboxPort):
    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    async def publish_envelope(self, envelope: EventEnvelope) -> None:
        self.envelopes.append(envelope)


class _EnrichOutageContextStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    @property
    def step_type(self) -> str:
        return "ip.stitch.enrich_outage"

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        return Result.ok(
            {
                "channel": "email",
                "template_id": "tpl_outage_restored",
                "recipient": "grid-ops@soopa.io",
                "variables": {
                    "meter_id": step_input.get("meter_id", "unknown"),
                    "run_id": context.run_id,
                },
            }
        )


class _PrepareNotificationInputHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Extracts notification parameters from aggregated parent payloads and delegates to EmitNotificationStepHandler."""

    def __init__(self, inner: EmitNotificationStepHandler) -> None:
        self._inner = inner

    @property
    def step_type(self) -> str:
        return StitchStepType.EMIT_NOTIFICATION.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.IDEMPOTENT_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        # Support either direct EmitNotificationStepInput or parent-aggregated payload
        if "channel" in step_input:
            return await self._inner.execute(context, step_input)
        parents = step_input.get("parents")
        if isinstance(parents, dict):
            for parent_data in parents.values():
                if isinstance(parent_data, dict):
                    if "channel" in parent_data:
                        return await self._inner.execute(context, parent_data)
                    nested_parents = parent_data.get("parents")
                    if isinstance(nested_parents, dict):
                        for nested in nested_parents.values():
                            if isinstance(nested, dict) and "channel" in nested:
                                return await self._inner.execute(context, nested)
        return await self._inner.execute(context, step_input)


def test_stitch_dto_codecs_validate_inputs_without_raising_exceptions() -> None:
    bad_q = QueryReplicaStepInput.from_payload({"connection_id": ""})
    assert bad_q.is_err

    good_q = QueryReplicaStepInput.from_payload(
        {
            "connection_id": "conn_1",
            "stream": "meters",
            "record_key": "rk_1",
        }
    )
    assert good_q.is_ok
    assert good_q.unwrap().stream == "meters"

    bad_notif = EmitNotificationStepInput.from_payload({"channel": "email"})
    assert bad_notif.is_err

    good_notif = EmitNotificationStepInput.from_payload(
        {
            "channel": "email",
            "template_id": "tpl_1",
            "recipient": "ops@soopa.io",
            "variables": {"k": "v"},
        }
    )
    assert good_notif.is_ok

    bad_http = ExecuteHttpActionStepInput.from_payload(
        {
            "connection_id": "",
            "stream_name": "orders",
            "operation": "CREATE",
            "payload": {"id": "ord-1"},
        }
    )
    assert bad_http.is_err

    good_http = ExecuteHttpActionStepInput.from_payload(
        {
            "connection_id": "conn_1",
            "stream_name": "orders",
            "operation": "UPSERT",
            "payload": {"id": "ord-1", "amount": 500},
            "record_id": "ord-1",
            "headers": {"X-Source": "Soopa"},
            "conflict_strategy": "IDEMPOTENT_SUCCESS",
        }
    )
    assert good_http.is_ok
    parsed_http = good_http.unwrap()
    assert parsed_http.operation == HttpWriteOperation.UPSERT.value
    assert parsed_http.record_id == "ord-1"
    assert parsed_http.headers == {"X-Source": "Soopa"}
    assert parsed_http.conflict_strategy == OutboundConflictStrategy.IDEMPOTENT_SUCCESS

    http_out = ExecuteHttpActionStepOutput(
        outbound_record_id="out_123",
        status="DELIVERED",
        record_id="ord-1",
        destination_id="sf_ord_1",
        response_status_code=200,
        response_body={"ok": True},
        was_deduplicated=False,
        was_token_refreshed=True,
    )
    payload_out = http_out.to_payload()
    assert payload_out["outbound_record_id"] == "out_123"
    assert payload_out["record_id"] == "ord-1"
    assert payload_out["was_deduplicated"] is False
    assert payload_out["was_token_refreshed"] is True


async def test_canonical_event_triggers_stitch_waits_for_signal_and_emits_stage1_notification() -> (
    None
):
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    uow = InMemoryWorkflowUnitOfWork()
    definitions = InMemoryWorkflowDefinitionRegistry()
    handlers = InMemoryStepHandlerRegistry()
    scheduler = WorkflowStepSchedulerService()
    error_policy = DefaultStepErrorPolicy()
    stitch_catalog = InMemoryStitchCatalogRegistry()
    outbox = _FakeNotificationOutbox()

    handlers.register(_EnrichOutageContextStepHandler())
    handlers.register(_PrepareNotificationInputHandler(EmitNotificationStepHandler(outbox)))

    defn = WorkflowDefinition(
        workflow_id="energy.outage_restoration_stitch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="enrich_outage",
                kind=NodeKind.TASK,
                step_type="ip.stitch.enrich_outage",
            ),
            NodeDefinition(
                node_key="wait_restored",
                kind=NodeKind.WAIT_FOR_EVENT,
                parents=("enrich_outage",),
                wait_event=WaitEventSpec(
                    event_key="canonical.meter_restored.normalized",
                    resource_hint_template="mtr_777",
                    timeout=timedelta(hours=2),
                ),
            ),
            NodeDefinition(
                node_key="notify_ops",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EMIT_NOTIFICATION.value,
                parents=("wait_restored",),
            ),
        ),
    )
    assert definitions.register(defn).is_ok

    # Register trigger subscription on `canonical.outage_event.normalized`
    stitch_catalog.register_subscription(
        StitchSubscription(
            id="sub_trigger_outage",
            tenant_id="ten_energy",
            workflow_id="energy.outage_restoration_stitch",
            workflow_version=1,
            canonical_event_type="canonical.outage_event.normalized",
            is_trigger=True,
            idempotency_key_field="outage_id",
            concurrency_key_field="meter_id",
        )
    )
    # Register signal subscription on `canonical.meter_restored.normalized`
    stitch_catalog.register_subscription(
        StitchSubscription(
            id="sub_signal_restored",
            tenant_id="ten_energy",
            workflow_id="energy.outage_restoration_stitch",
            workflow_version=1,
            canonical_event_type="canonical.meter_restored.normalized",
            is_trigger=False,
            condition_event_key="canonical.meter_restored.normalized",
            resource_hint_field="meter_id",
        )
    )

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

    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_catalog,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    worker_tick = ExecuteStitchWorkerTickUseCase(
        claim_steps_use_case=claim_steps,
        complete_step_use_case=complete_step,
        fail_step_use_case=fail_step,
        handler_registry=handlers,
    )

    # 1. Dispatch L3 Canonical Outage Event -> starts Stitch run
    disp1 = (
        await dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id="ten_energy",
                canonical_event_type="canonical.outage_event.normalized",
                event_id="evt_1",
                payload={"outage_id": "out_900", "meter_id": "mtr_777"},
                trace_id="trc_stitch_1",
                now=now,
            )
        )
    ).unwrap()
    assert len(disp1.started_run_ids) == 1
    run_id = disp1.started_run_ids[0]

    # Duplicate canonical event with same outage_id is deduplicated!
    disp_dup = (
        await dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id="ten_energy",
                canonical_event_type="canonical.outage_event.normalized",
                event_id="evt_2",
                payload={"outage_id": "out_900", "meter_id": "mtr_777"},
                trace_id="trc_stitch_1",
                now=now,
            )
        )
    ).unwrap()
    assert disp_dup.deduplicated_run_ids == (run_id,)

    # 2. Worker tick 1 claims and executes `enrich_outage` -> transitions `wait_restored` to WAITING
    tick1 = (
        await worker_tick.execute(
            ExecuteStitchWorkerTickCommand(
                worker_id="wrk_stitch_1",
                now=now + timedelta(seconds=1),
            )
        )
    ).unwrap()
    assert len(tick1.completed_step_ids) == 1

    run_after_tick1 = (await uow.runs.get_by_id("ten_energy", run_id)).unwrap()
    assert run_after_tick1.status == RunStatus.WAITING

    # 3. Dispatch L3 Canonical Meter Restored Event -> satisfies `wait_restored` and queues `notify_ops`!
    disp_signal = (
        await dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id="ten_energy",
                canonical_event_type="canonical.meter_restored.normalized",
                event_id="evt_3",
                payload={"meter_id": "mtr_777", "restored_at": "2026-10-25T12:05:00Z"},
                trace_id="trc_stitch_2",
                now=now + timedelta(minutes=5),
            )
        )
    ).unwrap()
    assert len(disp_signal.signalled_step_ids) == 1

    # 4. Worker tick 2 claims and executes `notify_ops` -> drops Stage-1 `notification.requested` envelope in outbox!
    tick2 = (
        await worker_tick.execute(
            ExecuteStitchWorkerTickCommand(
                worker_id="wrk_stitch_1",
                now=now + timedelta(minutes=5, seconds=1),
            )
        )
    ).unwrap()
    assert len(tick2.completed_step_ids) == 1

    final_run = (await uow.runs.get_by_id("ten_energy", run_id)).unwrap()
    assert final_run.status == RunStatus.SUCCEEDED
    assert len(outbox.envelopes) == 1
    assert outbox.envelopes[0].event_type == NotificationEventType.NOTIFICATION_TRIGGERED.value
    assert outbox.envelopes[0].idempotency_key == f"{run_id}:notify_ops:0"


async def test_query_replica_step_handler_and_worker_error_paths() -> None:
    now = datetime(2026, 10, 25, 13, 0, 0, tzinfo=UTC)
    lookup = _FakeReplicaLookup()
    rec = ReplicaRecord.create(
        tenant_id="ten_energy",
        connection_id="conn_ami",
        stream="meters",
        record_key="mtr_999",
        data={"voltage": 240.5, "status": "ONLINE"},
        trace_id="trc_rep_1",
    )
    lookup.add(rec)

    handler = QueryReplicaStepHandler(replica_lookup=lookup)
    assert handler.step_type == StitchStepType.QUERY_REPLICA.value
    assert handler.effect_policy == EffectPolicy.PURE

    ctx = StepContext(
        tenant_id="ten_energy",
        run_id="wfr_01",
        step_run_id="wfs_01",
        node_key="lookup_meter",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        idempotency_key="wfr_01:lookup_meter:0",
        trace_id="trc_01",
        correlation_id=None,
        deadline=now + timedelta(minutes=5),
    )

    # 1. Found replica record
    res_found = await handler.execute(
        ctx,
        {
            "connection_id": "conn_ami",
            "stream": "meters",
            "record_key": "mtr_999",
        },
    )
    assert res_found.is_ok
    assert res_found.unwrap()["found"] is True
    assert res_found.unwrap()["record_id"] == rec.id
    assert res_found.unwrap()["data"] == {"voltage": 240.5, "status": "ONLINE"}

    # 2. Missing replica record
    res_missing = await handler.execute(
        ctx,
        {
            "connection_id": "conn_ami",
            "stream": "meters",
            "record_key": "mtr_missing",
        },
    )
    assert res_missing.is_ok
    assert res_missing.unwrap()["found"] is False

    # 3. Invalid payload returns TerminalFailure Result without raising exceptions
    res_invalid = await handler.execute(ctx, {"connection_id": ""})
    assert res_invalid.is_err

    # 4. Worker tick with unregistered step handler fails step gracefully via Result
    uow = InMemoryWorkflowUnitOfWork()
    definitions = InMemoryWorkflowDefinitionRegistry()
    handlers = InMemoryStepHandlerRegistry()
    scheduler = WorkflowStepSchedulerService()
    error_policy = DefaultStepErrorPolicy()
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
    defn = WorkflowDefinition(
        workflow_id="energy.unregistered_step_stitch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="missing_step",
                kind=NodeKind.TASK,
                step_type="ip.stitch.missing_handler",
            ),
        ),
    )
    definitions.register(defn)
    stitch_catalog = InMemoryStitchCatalogRegistry()
    sub = StitchSubscription(
        id="sub_unreg",
        tenant_id="ten_energy",
        workflow_id="energy.unregistered_step_stitch",
        workflow_version=1,
        canonical_event_type="canonical.test.event",
        is_trigger=True,
    )
    stitch_catalog.register_subscription(sub)
    assert (
        len(
            stitch_catalog.list_subscriptions_for_event(
                tenant_id="ten_energy",
                canonical_event_type="canonical.test.event",
            )
        )
        == 1
    )

    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_catalog,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    await dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id="ten_energy",
            canonical_event_type="canonical.test.event",
            event_id="evt_99",
            payload={"k": "v"},
            trace_id="trc_99",
            now=now,
        )
    )
    worker_tick = ExecuteStitchWorkerTickUseCase(
        claim_steps_use_case=claim_steps,
        complete_step_use_case=complete_step,
        fail_step_use_case=fail_step,
        handler_registry=handlers,
    )
    tick_res = (
        await worker_tick.execute(ExecuteStitchWorkerTickCommand(worker_id="wrk_1", now=now))
    ).unwrap()
    assert len(tick_res.failed_or_retried_step_ids) == 1


class _CrashingStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    @property
    def step_type(self) -> str:
        return "ip.stitch.crash"

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        raise RuntimeError("Boom! Unhandled handler crash")


@pytest.mark.asyncio
async def test_stitch_worker_tick_catches_unhandled_handler_exception() -> None:
    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    uow = InMemoryWorkflowUnitOfWork()

    def uow_factory() -> InMemoryWorkflowUnitOfWork:
        return uow

    definitions = InMemoryWorkflowDefinitionRegistry()
    handlers = InMemoryStepHandlerRegistry()
    handlers.register(_CrashingStepHandler())

    sched = WorkflowStepSchedulerService()
    match_resolver = ResolveMatchConditionsUseCase(
        uow_factory=uow_factory,
        definition_registry=definitions,
        step_scheduler=sched,
    )
    start_run = StartRunUseCase(
        uow_factory=uow_factory,
        definition_registry=definitions,
        step_scheduler=sched,
    )
    claim_steps = ClaimStepsUseCase(
        uow_factory=uow_factory,
        definition_registry=definitions,
        step_scheduler=sched,
        match_resolver=match_resolver,
    )
    complete_step = CompleteStepUseCase(
        uow_factory=uow_factory,
        definition_registry=definitions,
        step_scheduler=sched,
        match_resolver=match_resolver,
    )
    fail_step = FailStepUseCase(
        uow_factory=uow_factory,
        definition_registry=definitions,
        error_policy=DefaultStepErrorPolicy(),
        step_scheduler=sched,
        match_resolver=match_resolver,
    )

    defn = WorkflowDefinition(
        workflow_id="energy.crash_stitch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="step_crash",
                step_type="ip.stitch.crash",
                kind=NodeKind.TASK,
            ),
        ),
    )
    definitions.register(defn)
    stitch_catalog = InMemoryStitchCatalogRegistry()
    sub = StitchSubscription(
        id="sub_crash",
        tenant_id="ten_energy",
        workflow_id="energy.crash_stitch",
        workflow_version=1,
        canonical_event_type="canonical.test.event",
        is_trigger=True,
    )
    stitch_catalog.register_subscription(sub)

    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_catalog,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    await dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id="ten_energy",
            canonical_event_type="canonical.test.event",
            event_id="evt_crash",
            payload={"k": "v"},
            trace_id="trc_crash",
            now=now,
        )
    )
    worker_tick = ExecuteStitchWorkerTickUseCase(
        claim_steps_use_case=claim_steps,
        complete_step_use_case=complete_step,
        fail_step_use_case=fail_step,
        handler_registry=handlers,
    )
    tick_res = (
        await worker_tick.execute(ExecuteStitchWorkerTickCommand(worker_id="wrk_1", now=now))
    ).unwrap()
    assert len(tick_res.completed_step_ids) == 0
    assert len(tick_res.failed_or_retried_step_ids) == 1
