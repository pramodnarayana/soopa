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
from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundConflictStrategy,
)
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import (
    EmitNotificationStepInput,
    ExecuteHttpActionStepInput,
    ExecuteHttpActionStepOutput,
    QueryReplicaStepInput,
    Stitch,
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


class _EnrichIncidentContextStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    @property
    def step_type(self) -> str:
        return "ip.stitch.enrich_incident"

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        return Result.ok(
            {
                "channel": "email",
                "template_id": "tpl_incident_resolved",
                "recipient": "ops-team@soopa.io",
                "variables": {
                    "resource_id": step_input.get("resource_id", "unknown"),
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
            "stream": "records_alpha",
            "record_key": "rk_1",
        }
    )
    assert good_q.is_ok
    assert good_q.unwrap().stream == "records_alpha"

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


async def test_canonical_event_triggers_stitch_through_signal_resolution_to_stage1_notification() -> (
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

    handlers.register(_EnrichIncidentContextStepHandler())
    handlers.register(_PrepareNotificationInputHandler(EmitNotificationStepHandler(outbox)))

    defn = WorkflowDefinition(
        workflow_id="synthetic.incident_resolution_stitch",
        version=1,
        nodes=(
            NodeDefinition(
                node_key="enrich_incident",
                kind=NodeKind.TASK,
                step_type="ip.stitch.enrich_incident",
            ),
            NodeDefinition(
                node_key="wait_resolved",
                kind=NodeKind.WAIT_FOR_EVENT,
                parents=("enrich_incident",),
                wait_event=WaitEventSpec(
                    event_key="canonical.resource_resolved.normalized",
                    resource_hint_template="res_777",
                    timeout=timedelta(hours=2),
                ),
            ),
            NodeDefinition(
                node_key="notify_ops",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EMIT_NOTIFICATION.value,
                parents=("wait_resolved",),
            ),
        ),
    )
    assert definitions.register(defn).is_ok

    # Register trigger stitch on `canonical.incident_event.normalized`
    stitch_catalog.register_stitch(
        Stitch(
            id="sub_trigger_incident",
            tenant_id="ten_alpha",
            workflow_id="synthetic.incident_resolution_stitch",
            workflow_version=1,
            canonical_event_type="canonical.incident_event.normalized",
            is_trigger=True,
            idempotency_key_field="incident_id",
            concurrency_key_field="resource_id",
        )
    )
    # Register signal stitch on `canonical.resource_resolved.normalized`
    stitch_catalog.register_stitch(
        Stitch(
            id="sub_signal_resolved",
            tenant_id="ten_alpha",
            workflow_id="synthetic.incident_resolution_stitch",
            workflow_version=1,
            canonical_event_type="canonical.resource_resolved.normalized",
            is_trigger=False,
            condition_event_key="canonical.resource_resolved.normalized",
            resource_hint_field="resource_id",
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

    # 1. Dispatch L3 Canonical Incident Event -> starts Stitch run
    disp1 = (
        await dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id="ten_alpha",
                canonical_event_type="canonical.incident_event.normalized",
                event_id="evt_1",
                payload={"incident_id": "inc_900", "resource_id": "res_777"},
                trace_id="trc_stitch_1",
                now=now,
            )
        )
    ).unwrap()
    assert len(disp1.started_run_ids) == 1
    run_id = disp1.started_run_ids[0]

    # Duplicate canonical event with same incident_id is deduplicated!
    disp_dup = (
        await dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id="ten_alpha",
                canonical_event_type="canonical.incident_event.normalized",
                event_id="evt_2",
                payload={"incident_id": "inc_900", "resource_id": "res_777"},
                trace_id="trc_stitch_1",
                now=now,
            )
        )
    ).unwrap()
    assert disp_dup.deduplicated_run_ids == (run_id,)

    # 2. Worker tick 1 claims and executes `enrich_incident` -> transitions `wait_resolved` to WAITING
    tick1 = (
        await worker_tick.execute(
            ExecuteStitchWorkerTickCommand(
                worker_id="wrk_stitch_1",
                now=now + timedelta(seconds=1),
            )
        )
    ).unwrap()
    assert len(tick1.completed_step_ids) == 1

    run_after_tick1 = (await uow.runs.get_by_id("ten_alpha", run_id)).unwrap()
    assert run_after_tick1.status == RunStatus.WAITING

    # 3. Dispatch L3 Canonical Resource Resolved Event -> satisfies `wait_resolved` and queues `notify_ops`!
    disp_signal = (
        await dispatcher.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id="ten_alpha",
                canonical_event_type="canonical.resource_resolved.normalized",
                event_id="evt_3",
                payload={"resource_id": "res_777", "resolved_at": "2026-10-25T12:05:00Z"},
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

    final_run = (await uow.runs.get_by_id("ten_alpha", run_id)).unwrap()
    assert final_run.status == RunStatus.SUCCEEDED
    assert len(outbox.envelopes) == 1
    assert outbox.envelopes[0].event_type == NotificationEventType.NOTIFICATION_TRIGGERED.value
    assert outbox.envelopes[0].idempotency_key == f"{run_id}:notify_ops:0"
    notif_data = outbox.envelopes[0].payload.get("notification_data")
    assert isinstance(notif_data, dict)
    assert notif_data.get("event_id") == f"{run_id}:notify_ops:0"


async def test_query_replica_step_handler_resolves_replica_snapshots() -> None:
    now = datetime(2026, 10, 25, 13, 0, 0, tzinfo=UTC)
    lookup = _FakeReplicaLookup()
    rec = ReplicaRecord.create(
        tenant_id="ten_alpha",
        connection_id="conn_source",
        stream="records_alpha",
        record_key="rec_999",
        data={"quantity": 240.5, "status": "ONLINE"},
        trace_id="trc_rep_1",
    )
    lookup.add(rec)

    handler = QueryReplicaStepHandler(replica_lookup=lookup)
    assert handler.step_type == StitchStepType.QUERY_REPLICA.value
    assert handler.effect_policy == EffectPolicy.PURE

    ctx = StepContext(
        tenant_id="ten_alpha",
        run_id="wfr_01",
        step_run_id="wfs_01",
        node_key="lookup_record",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        idempotency_key="wfr_01:lookup_record:0",
        trace_id="trc_01",
        correlation_id=None,
        deadline=now + timedelta(minutes=5),
    )

    # 1. Found replica record
    res_found = await handler.execute(
        ctx,
        {
            "connection_id": "conn_source",
            "stream": "records_alpha",
            "record_key": "rec_999",
        },
    )
    assert res_found.is_ok
    assert res_found.unwrap()["found"] is True
    assert res_found.unwrap()["record_id"] == rec.id
    assert res_found.unwrap()["data"] == {"quantity": 240.5, "status": "ONLINE"}

    # 2. Missing replica record
    res_missing = await handler.execute(
        ctx,
        {
            "connection_id": "conn_source",
            "stream": "records_alpha",
            "record_key": "rec_missing",
        },
    )
    assert res_missing.is_ok
    assert res_missing.unwrap()["found"] is False

    # 3. Invalid payload returns TerminalFailure Result without raising exceptions
    res_invalid = await handler.execute(ctx, {"connection_id": ""})
    assert res_invalid.is_err


async def test_stitch_worker_tick_marks_unregistered_step_handler_failed() -> None:
    now = datetime(2026, 10, 25, 13, 0, 0, tzinfo=UTC)
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
        workflow_id="synthetic.unregistered_step_stitch",
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
    sub = Stitch(
        id="sub_unreg",
        tenant_id="ten_alpha",
        workflow_id="synthetic.unregistered_step_stitch",
        workflow_version=1,
        canonical_event_type="canonical.test.event",
        is_trigger=True,
    )
    stitch_catalog.register_stitch(sub)
    assert (
        len(
            stitch_catalog.list_stitches_for_event(
                tenant_id="ten_alpha",
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
            tenant_id="ten_alpha",
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
        workflow_id="synthetic.crash_stitch",
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
    sub = Stitch(
        id="sub_crash",
        tenant_id="ten_alpha",
        workflow_id="synthetic.crash_stitch",
        workflow_version=1,
        canonical_event_type="canonical.test.event",
        is_trigger=True,
    )
    stitch_catalog.register_stitch(sub)

    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_catalog,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    await dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id="ten_alpha",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload_status", "payload_region"),
    [
        ("DRAFT", "EU"),
        ("APPROVED", "US"),
    ],
)
async def test_stitch_filter_conditions_skip_non_matching_canonical_payload(
    payload_status: str,
    payload_region: str,
) -> None:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    uow = InMemoryWorkflowUnitOfWork()
    definitions = InMemoryWorkflowDefinitionRegistry()
    sched = WorkflowStepSchedulerService()
    start_run = StartRunUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=sched,
    )
    match_resolver = ResolveMatchConditionsUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=sched,
    )
    definitions.register(
        WorkflowDefinition(
            workflow_id="synthetic.filtered_stitch",
            version=1,
            nodes=(
                NodeDefinition(
                    node_key="step_one",
                    step_type="ip.stitch.noop",
                    kind=NodeKind.TASK,
                ),
            ),
        )
    )
    stitch_catalog = InMemoryStitchCatalogRegistry()
    stitch_catalog.register_stitch(
        Stitch(
            id="ip_stc_filtered_1",
            tenant_id="ten_alpha",
            workflow_id="synthetic.filtered_stitch",
            workflow_version=1,
            canonical_event_type="canonical.order.v1",
            is_trigger=True,
            filter_conditions={"status": "APPROVED", "region": "EU"},
        )
    )
    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_catalog,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    res = await dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id="ten_alpha",
            canonical_event_type="canonical.order.v1",
            event_id=f"evt_{payload_status}_{payload_region}",
            payload={"id": "ORD-1", "status": payload_status, "region": payload_region},
            trace_id="trc_filter_skip",
            now=now,
        )
    )
    assert res.is_ok
    dto = res.unwrap()
    assert dto.started_run_ids == ()
    assert dto.deduplicated_run_ids == ()


@pytest.mark.asyncio
async def test_stitch_filter_conditions_start_run_on_matching_canonical_payload() -> None:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    uow = InMemoryWorkflowUnitOfWork()
    definitions = InMemoryWorkflowDefinitionRegistry()
    sched = WorkflowStepSchedulerService()
    start_run = StartRunUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=sched,
    )
    match_resolver = ResolveMatchConditionsUseCase(
        uow_factory=lambda: uow,
        definition_registry=definitions,
        step_scheduler=sched,
    )
    definitions.register(
        WorkflowDefinition(
            workflow_id="synthetic.filtered_stitch",
            version=1,
            nodes=(
                NodeDefinition(
                    node_key="step_one",
                    step_type="ip.stitch.noop",
                    kind=NodeKind.TASK,
                ),
            ),
        )
    )
    stitch_catalog = InMemoryStitchCatalogRegistry()
    stitch_catalog.register_stitch(
        Stitch(
            id="ip_stc_filtered_2",
            tenant_id="ten_alpha",
            workflow_id="synthetic.filtered_stitch",
            workflow_version=1,
            canonical_event_type="canonical.order.v1",
            is_trigger=True,
            filter_conditions={"status": "APPROVED", "region": "EU"},
        )
    )
    dispatcher = DispatchCanonicalEventToStitchesUseCase(
        stitch_catalog=stitch_catalog,
        start_run_use_case=start_run,
        resolve_matches_use_case=match_resolver,
    )
    res = await dispatcher.execute(
        DispatchCanonicalEventToStitchesCommand(
            tenant_id="ten_alpha",
            canonical_event_type="canonical.order.v1",
            event_id="evt_approved_order",
            payload={"id": "ORD-2", "status": "APPROVED", "region": "EU"},
            trace_id="trc_filter_match",
            now=now,
        )
    )
    assert res.is_ok
    dto = res.unwrap()
    assert len(dto.started_run_ids) == 1
