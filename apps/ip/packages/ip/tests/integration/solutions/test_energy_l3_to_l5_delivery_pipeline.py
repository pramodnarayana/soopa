"""End-to-End Layer 3 to Layer 5 Energy Delivery Pipeline Integration Tests on real PostgreSQL.

Exercises the complete Layer 3 (Canonical MDM Normalization) -> Layer 4 (Stitch Workflow Orchestration)
-> Layer 5 (Outbound Egress Delivery to Universal Schema Simulator / ERP Destination) pipeline under
SAVEPOINT-isolated transactions (global_session, tenant_session, transactional_router).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime
from typing import Final

import pytest
from database.outbox_serializer import serialize_domain_event
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from dependency_injector import providers
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from identity.domain.authorization import StandardRole
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_cipher,
    get_ip_global_session,
    require_flows_write,
    require_tenant_member,
)
from ip.engine.adapters.inbound.workers import (
    IpBackfillStreamNormalizationExecutorPort,
    IpDeliveryRouteRegistry,
    IpFetchRecordExecutorPort,
    IpNormalizeReplicaExecutorPort,
    IpOrchestratorRouteRegistry,
    IpProcessInboundRangeExecutorPort,
    IpRunSyncExecutorPort,
)
from ip.engine.adapters.outbound.database.data_plane.mappers import (
    outbound_record_to_domain,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
    NormalizedRecordModel,
    OutboundRecordModel,
)
from ip.engine.adapters.outbound.database.tenant_resolver import (
    SqlAlchemyIpTenantResolver,
)
from ip.engine.adapters.outbound.stitches import ExecuteHttpActionStepHandler
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
)
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordResponse,
    DeliverOutboundRecordUseCase,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordResultDTO,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncResultDTO,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationResultDTO,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
)
from ip.engine.application.use_cases.normalization.process_inbound_range_use_case import (
    ProcessInboundRangeCommand,
    ProcessInboundRangeResultDTO,
)
from ip.engine.bootstrap.container import (
    Container,
    create_ip_stitch_dispatcher,
    create_ip_stitch_worker_tick,
)
from ip.engine.bootstrap.publisher_factory import build_ip_dp_outbox_router
from ip.engine.domain.constants import DEFAULT_MAX_CAUSATION_DEPTH
from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundDispatchStatus,
)
from ip.engine.domain.enums import IpOutboxSource
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.replication.enums import FetchRecordStatus, SyncRunStatus
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import (
    Stitch,
)
from ip.engine.domain.trace.enums import IpTraceEventType
from ip.module import IpApiModule
from ip.solutions.bootstrap import (
    configure_solution_container,
)
from ip.solutions.domains.energy.canonical import EnergyEntityType
from ip.solutions.domains.energy.models import MdmMeterReadingRecord
from orchestration.adapters.outbound.database.models import (
    WorkflowRunModel,
    WorkflowStepRunModel,
)
from orchestration.application.services import InMemoryStepHandlerRegistry
from orchestration.domain.constants import (
    EffectPolicy,
    NodeKind,
    Priority,
    RunStatus,
    StepStatus,
)
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.exceptions import Result as WorkflowResult
from orchestration.domain.failures import StepFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import (
    MultiShardOutboxDrainRelay,
)
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from security.provider import SecurityProvider
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope
from seedwork.utils import generate_id
from sqlalchemy import select

pytestmark = pytest.mark.integration

_TEST_KEY_BYTES: Final[bytes] = b"0123456789abcdef0123456789abcdef"
_WORKFLOW_ID: Final[str] = "energy.meter_reading_erp_delivery_stitch"
_STITCH_ID: Final[str] = "stch_energy_reading_to_erp"
_PREPARE_STEP_TYPE: Final[str] = "energy.prepare_erp_dispatch"


class _InMemoryQueueBridgePublisher(OutboxPublisherPort):
    """Directly bridges published Outbox events into an EventEnvelopeDispatcher."""

    def __init__(self, dispatcher: EventEnvelopeDispatcher) -> None:
        self._dispatcher = dispatcher
        self.published_envelopes: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published_envelopes.append(event)
        await self._dispatcher.dispatch_envelope(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        self.published_envelopes.extend(events)
        for evt in events:
            await self._dispatcher.dispatch_envelope(evt)
        return [e.id for e in events]


class _NoopFetchExecutor(IpFetchRecordExecutorPort):
    async def execute(self, command: FetchRecordCommand) -> Result[FetchRecordResultDTO, IpError]:
        return Result.ok(
            FetchRecordResultDTO(
                status=FetchRecordStatus.SUCCEEDED,
                trace_id=command.trace_id,
            )
        )


class _NoopRunSyncExecutor(IpRunSyncExecutorPort):
    async def execute(self, command: RunSyncCommand) -> Result[RunSyncResultDTO, IpError]:
        return Result.ok(
            RunSyncResultDTO(
                status=SyncRunStatus.SUCCEEDED,
                run_id="noop_run",
                trace_id=command.trace_id,
            )
        )


class _NoopNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        return Result.ok(
            NormalizeReplicaRecordResultDTO(
                canonical_record_ids=(),
                rejections=(),
                status="NOOP",
                trace_id=command.trace_id,
            )
        )


class _NoopBackfillExecutor(IpBackfillStreamNormalizationExecutorPort):
    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        return Result.ok(
            BackfillStreamNormalizationResultDTO(
                processed_count=0,
                normalized_count=0,
                rejected_count=0,
                status="COMPLETED",
            )
        )


class _NoopRangeExecutor(IpProcessInboundRangeExecutorPort):
    async def execute(
        self, command: ProcessInboundRangeCommand
    ) -> Result[ProcessInboundRangeResultDTO, IpError]:
        return Result.ok(
            ProcessInboundRangeResultDTO(
                batch_id=command.inbound_batch_id,
                stream_name=command.stream_name,
                item_count=0,
                replica_record_ids=(),
                canonical_record_ids=(),
                trace_id=command.trace_id,
            )
        )


class _EnergyPrepareErpDispatchStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Pure Stitch DAG step mapping canonical AMI meter reading into ERP billing payload."""

    def __init__(self, dest_connection_id: str) -> None:
        self._dest_connection_id = dest_connection_id

    @property
    def step_type(self) -> str:
        return _PREPARE_STEP_TYPE

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> WorkflowResult[JsonDict, StepFailure]:
        _ = context
        meter_serial = str(step_input.get("meter_serial_number", "MTR-UNKNOWN"))
        raw_ts = str(step_input.get("reading_timestamp", "2026-11-12T12:00:00Z"))
        raw_kwh = step_input.get("kwh_delivered", 0.0)
        kwh = float(raw_kwh) if isinstance(raw_kwh, (int, float)) else 0.0
        sp_id = step_input.get("service_point_id")

        sanitized_ts = raw_ts.replace(":", "_")
        return WorkflowResult.ok(
            {
                "destination_connection_id": self._dest_connection_id,
                "destination_stream": "billing_readings",
                "operation": HttpWriteOperation.CREATE.value,
                "record_id": f"{meter_serial}:{raw_ts}",
                "payload": {
                    "reading_id": f"BILL-RDG-{meter_serial}-{sanitized_ts}",
                    "meter_serial": meter_serial,
                    "kwh_delivered": kwh,
                    "reading_timestamp": raw_ts,
                    "service_point_id": str(sp_id) if sp_id else None,
                },
            }
        )


def _configure_test_container(transactional_router: TransactionalTestRouter) -> Container:
    resolver = SqlAlchemyIpTenantResolver(transactional_router)
    container = configure_solution_container(Container())
    container.config.allow_private_ips.from_value(True)
    container.db_router.override(providers.Object(transactional_router))
    container.tenant_resolver.override(providers.Object(resolver))
    return container


def _build_test_app(
    *,
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
    active_identity: dict[str, IdentityContext],
) -> FastAPI:
    app = FastAPI()
    module = IpApiModule()
    module.register_routes(app)
    app.state.db_router = transactional_router
    cipher = SecurityProvider.get_cipher(key=_TEST_KEY_BYTES)

    async def _override_global_session() -> AsyncGenerator[GlobalSession, None]:
        yield global_session

    def _override_identity(request: Request) -> IdentityContext:
        ctx = active_identity["current"]
        request.state.identity = ctx
        request.state.ucp_tenant_id = ctx.tenant_id or ""
        return ctx

    app.dependency_overrides[get_ip_global_session] = _override_global_session
    app.dependency_overrides[require_tenant_member] = _override_identity
    app.dependency_overrides[require_flows_write] = _override_identity
    app.dependency_overrides[get_cipher] = lambda: cipher
    return app


def _build_l3_to_l5_outbox_drain_pipeline(
    *,
    container: Container,
    transactional_router: TransactionalTestRouter,
) -> tuple[
    MultiShardOutboxDrainRelay,
    _InMemoryQueueBridgePublisher,
    _InMemoryQueueBridgePublisher,
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
]:
    dp_uow_provider = container.dp_uow_provider()
    stitch_dispatcher = create_ip_stitch_dispatcher(
        db_router=transactional_router,
        dp_uow_provider=dp_uow_provider,
        stitch_catalog=container.stitch_catalog(),
        definition_registry=container.workflow_definition_registry(),
    )
    stitch_worker_tick = create_ip_stitch_worker_tick(
        db_router=transactional_router,
        definition_registry=container.workflow_definition_registry(),
        handler_registry=container.step_handler_registry(),
    )

    orch_dispatcher = EventEnvelopeDispatcher()
    orch_registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        stitch_dispatcher=stitch_dispatcher,
        stitch_worker_tick=stitch_worker_tick,
        normalize_use_case=_NoopNormalizeExecutor(),
        backfill_use_case=_NoopBackfillExecutor(),
        process_inbound_range_use_case=_NoopRangeExecutor(),
        stream_definition_resolver=None,
        max_chunk_concurrency=4,
    )
    orch_registry.register_routes(orch_dispatcher)
    orch_bridge = _InMemoryQueueBridgePublisher(orch_dispatcher)

    delivery_dispatcher = EventEnvelopeDispatcher()
    delivery_registry = IpDeliveryRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        deliver_outbound_use_case=container.session_scoped_outbound_delivery(),
        fetch_record_use_case=_NoopFetchExecutor(),
        run_sync_use_case=_NoopRunSyncExecutor(),
        tiered_storage=container.tiered_storage(),
        max_chunk_concurrency=4,
    )
    delivery_registry.register_routes(delivery_dispatcher)
    delivery_bridge = _InMemoryQueueBridgePublisher(delivery_dispatcher)

    noop_bridge = _InMemoryQueueBridgePublisher(EventEnvelopeDispatcher())
    dp_router = build_ip_dp_outbox_router(
        orchestrator_realtime_publisher=orch_bridge,
        orchestrator_bulk_publisher=orch_bridge,
        delivery_realtime_publisher=delivery_bridge,
        delivery_bulk_publisher=delivery_bridge,
        notification_publisher=noop_bridge,
        events_topic_publisher=noop_bridge,
    )
    dp_outbox_repo = SqlAlchemyShardedOutboxRepository(
        transactional_router,
        app_slug="ip",
        model_cls=IpDataPlaneOutboxRecord,
        source=IpOutboxSource.DATA_PLANE.value,
    )
    drain_relay = MultiShardOutboxDrainRelay(
        repository=dp_outbox_repo,
        publisher=dp_router,
        batch_size=100,
    )
    return (
        drain_relay,
        orch_bridge,
        delivery_bridge,
        stitch_dispatcher,
        stitch_worker_tick,
    )


async def _drain_outbox_fully(
    drain_relay: MultiShardOutboxDrainRelay,
    max_iterations: int = 6,
) -> None:
    for _ in range(max_iterations):
        drained = await drain_relay.drain_all_shards_once()
        if drained == 0:
            break


async def _provision_erp_destination_connection(
    client: AsyncClient,
    tenant_id: str,
) -> str:
    """Provisions an ERP Destination Connection via Universal Simulator with a billing_readings blueprint."""
    check_resp = await client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/check",
        json={
            "app_id": "universal_simulator",
            "auth_type": "NO_AUTH",
            "public_config": {"seed": 3003, "records_per_pull": 5},
            "raw_credentials": {},
        },
    )
    assert check_resp.status_code == 200

    conn_resp = await client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "universal_simulator",
            "name": "Utility CIS ERP Simulator",
            "auth_type": "NO_AUTH",
            "public_config": {"seed": 3003, "records_per_pull": 5},
            "raw_credentials": {},
            "endpoint_for_fingerprint": "Utility CIS ERP Simulator",
        },
    )
    assert conn_resp.status_code == 201
    dest_conn_id: str = conn_resp.json()["id"]

    ent_resp = await client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{dest_conn_id}/simulator/entities",
        json={
            "entity_name": "billing_readings",
            "primary_key_field": "reading_id",
            "cursor_field": "reading_timestamp",
            "sample_blueprint": {
                "reading_id": "BILL-RDG-1001",
                "meter_serial": "MTR-5001",
                "kwh_delivered": 14.5,
                "reading_timestamp": "2026-11-12T10:00:00Z",
                "service_point_id": "SP-1001",
            },
            "records_per_pull": 5,
        },
    )
    assert ent_resp.status_code == 201
    return dest_conn_id


def _register_energy_erp_delivery_workflow_and_stitch(
    *,
    container: Container,
    tenant_id: str,
    dest_connection_id: str,
) -> None:
    """Registers the Energy Delivery Workflow DAG and its trigger Stitch in the test container."""
    step_registry = container.step_handler_registry()
    assert isinstance(step_registry, InMemoryStepHandlerRegistry)
    step_registry.register(_EnergyPrepareErpDispatchStepHandler(dest_connection_id))

    wf_defn = WorkflowDefinition(
        workflow_id=_WORKFLOW_ID,
        version=1,
        default_priority=Priority.REALTIME,
        description="Delivers normalized AMI interval meter readings to utility ERP billing.",
        nodes=(
            NodeDefinition(
                node_key="prepare_erp_payload",
                kind=NodeKind.TASK,
                step_type=_PREPARE_STEP_TYPE,
                effect_policy=EffectPolicy.PURE,
            ),
            NodeDefinition(
                node_key="dispatch_erp_reading",
                kind=NodeKind.TASK,
                step_type=StitchStepType.EXECUTE_HTTP_ACTION.value,
                parents=("prepare_erp_payload",),
                effect_policy=EffectPolicy.RECONCILABLE_EFFECT,
            ),
        ),
    )
    wf_registry = container.workflow_definition_registry()
    assert wf_registry.register(wf_defn).is_ok

    stitch = Stitch(
        id=_STITCH_ID,
        tenant_id=tenant_id,
        workflow_id=_WORKFLOW_ID,
        workflow_version=1,
        canonical_event_type=EnergyEntityType.MDM_METER_READING.value,
        is_trigger=True,
        idempotency_key_field="source_id",
        concurrency_key_field="meter_serial_number",
        is_active=True,
    )
    stitch_catalog = container.stitch_catalog()
    stitch_catalog.register_stitch(stitch)


async def _seed_l3_canonical_meter_reading(
    *,
    tenant_session: TenantSession,
    tenant_id: str,
    source_connection_id: str,
    meter_serial: str,
    service_point_id: str,
    reading_timestamp_iso: str,
    kwh_delivered: float,
    trace_id: str,
) -> str:
    """Seeds an L3 Canonical Meter Reading and emits a CANONICAL_RECORD_CHANGED outbox event."""
    source_id = f"{meter_serial}:{reading_timestamp_iso}"
    dt_ts = datetime.fromisoformat(reading_timestamp_iso.replace("Z", "+00:00"))

    canonical_mr = MdmMeterReadingRecord(
        id=f"mr_{meter_serial}",
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=meter_serial,
        source_connection_id=source_connection_id,
        source_replica_id=f"rep_{meter_serial}",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        meter_serial_number=meter_serial,
        service_point_id=service_point_id,
        reading_timestamp=dt_ts,
        interval_minutes=15,
        kwh_delivered=kwh_delivered,
        kwh_received=0.0,
        quality_flag="VALIDATED",
        recorded_at=dt_ts,
    )
    tenant_session.add(canonical_mr)

    norm_record = NormalizedRecord.create(
        tenant_id=tenant_id,
        connection_id=source_connection_id,
        canonical_type=EnergyEntityType.MDM_METER_READING.value,
        source_id=source_id,
        canonical_data={
            "meter_serial_number": meter_serial,
            "service_point_id": service_point_id,
            "reading_timestamp": reading_timestamp_iso,
            "interval_minutes": 15,
            "kwh_delivered": kwh_delivered,
            "kwh_received": 0.0,
            "quality_flag": "VALIDATED",
        },
        trace_id=trace_id,
        correlation_id=meter_serial,
    )
    norm_orm = NormalizedRecordModel(
        id=norm_record.id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=meter_serial,
        connection_id=source_connection_id,
        canonical_type=EnergyEntityType.MDM_METER_READING.value,
        source_id=source_id,
        canonical_data=norm_record.canonical_data,
        normalized_at=norm_record.normalized_at,
    )
    tenant_session.add(norm_orm)

    canonical_event = CanonicalRecordChangedEvent(
        tenant_id=tenant_id,
        connection_id=source_connection_id,
        canonical_type=EnergyEntityType.MDM_METER_READING.value,
        source_id=source_id,
        action="UPSERT",
        trace_id=trace_id,
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        record_ids=(source_id,),
    )
    outbox_event = IpDataPlaneOutboxRecord(
        id=generate_id(IpDataPlaneOutboxRecord.ID_PREFIX),
        idempotency_key=f"idem_canon_{source_id}",
        tenant_id=tenant_id,
        event_type=canonical_event.event_name,
        trace_id=canonical_event.trace_id,
        correlation_id=canonical_event.correlation_id,
        lane=canonical_event.get_processing_lane().value,
        payload=serialize_domain_event(canonical_event),
        status=OutboxStatus.PENDING,
    )
    tenant_session.add(outbox_event)
    await tenant_session.flush()
    return source_id


def _assert_workflow_and_outbound_delivery_outcomes(
    *,
    workflow_runs: Sequence[WorkflowRunModel],
    workflow_steps: Sequence[WorkflowStepRunModel],
    outbound_records: Sequence[OutboundRecordModel],
    trace_events: Sequence[IpTraceEventModel],
    dest_connection_id: str,
    meter_serial: str,
) -> None:
    """Verifies that the Workflow completed and the OutboundRecord was delivered with trace auditability."""
    assert len(workflow_runs) >= 1
    latest_run = workflow_runs[0]
    assert latest_run.workflow_id == _WORKFLOW_ID
    assert latest_run.status == RunStatus.SUCCEEDED.value

    step_statuses = {s.node_key: s.status for s in workflow_steps}
    assert step_statuses.get("prepare_erp_payload") == StepStatus.SUCCEEDED.value
    assert step_statuses.get("dispatch_erp_reading") == StepStatus.SUCCEEDED.value

    assert len(outbound_records) >= 1
    delivered = outbound_records[0]
    assert delivered.connection_id == dest_connection_id
    assert delivered.stream_name == "billing_readings"
    assert delivered.status == OutboundDispatchStatus.DELIVERED.value
    assert delivered.response_status_code == 200
    assert delivered.duration_ms is not None and delivered.duration_ms > 0
    assert delivered.response_body is not None
    assert delivered.response_body.get("status") == "ACCEPTED"
    assert "sim_dest_" in str(delivered.response_body.get("destination_id"))

    domain_outbound = outbound_record_to_domain(delivered)
    assert domain_outbound.request_body is not None
    assert domain_outbound.request_body.get("meter_serial") == meter_serial

    trace_types = {e.event_type for e in trace_events}
    assert IpTraceEventType.DISPATCH_PENDING.value in trace_types
    assert IpTraceEventType.DISPATCH_DELIVERED.value in trace_types


@pytest.mark.asyncio
async def test_energy_l3_to_l5_stitch_orchestration_outbound_delivery(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Verifies complete Energy L3-L5 pipeline: Canonical MDM -> Stitch DAG -> L5 Outbound Delivery."""
    admin_ctx = IdentityContext(
        subject="usr_energy_ops",
        claims={},
        tenant_id=seeded_ip_tenant,
        authorized_tenants={seeded_ip_tenant},
        roles=(StandardRole.TENANT_ADMIN.value,),
    )
    active_identity: dict[str, IdentityContext] = {"current": admin_ctx}
    app = _build_test_app(
        global_session=global_session,
        transactional_router=transactional_router,
        active_identity=active_identity,
    )
    container = _configure_test_container(transactional_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Provision Destination Connection (Utility ERP Billing Simulator)
        dest_conn_id = await _provision_erp_destination_connection(client, seeded_ip_tenant)

    # 2. Register Energy Delivery Workflow DAG & Trigger Stitch
    _register_energy_erp_delivery_workflow_and_stitch(
        container=container,
        tenant_id=seeded_ip_tenant,
        dest_connection_id=dest_conn_id,
    )

    # 3. Assemble Dual-Worker Outbox Drain Pipeline
    (
        drain_relay,
        orch_bridge,
        delivery_bridge,
        _stitch_dispatcher,
        _stitch_worker_tick,
    ) = _build_l3_to_l5_outbox_drain_pipeline(
        container=container,
        transactional_router=transactional_router,
    )

    # 4. Seed Canonical Meter Reading and emit CANONICAL_RECORD_CHANGED outbox event
    meter_serial = "MTR-ENERGY-8001"
    trace_id = "ip_trc_energy_l3_to_l5_01"
    await _seed_l3_canonical_meter_reading(
        tenant_session=tenant_session,
        tenant_id=seeded_ip_tenant,
        source_connection_id="conn_ami_source_test",
        meter_serial=meter_serial,
        service_point_id="SP-ENERGY-8001",
        reading_timestamp_iso="2026-11-12T12:00:00Z",
        kwh_delivered=28.75,
        trace_id=trace_id,
    )

    # 5. Execute 2-Queue Outbox Drain Pipeline
    # Cycle 1: Orchestrator drains CANONICAL_RECORD_CHANGED -> triggers Stitch -> completes steps -> stages OutboundRecord
    # Cycle 2: Delivery Worker drains OUTBOUND_RECORD_CREATED -> executes HTTP action -> marks DELIVERED
    await _drain_outbox_fully(drain_relay, max_iterations=6)

    # 6. Verify Outbox Envelopes Dispatched Across Dual-Queue Boundaries
    orch_types = [e.event_type for e in orch_bridge.published_envelopes]
    delivery_types = [e.event_type for e in delivery_bridge.published_envelopes]
    assert "ip.canonical_record.changed" in orch_types
    assert "ip.outbound_record.created" in delivery_types

    # 7. Query Persisted State and Validate Assertions
    wf_runs = (
        (
            await tenant_session.execute(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.tenant_id == seeded_ip_tenant,
                    WorkflowRunModel.workflow_id == _WORKFLOW_ID,
                )
            )
        )
        .scalars()
        .all()
    )

    wf_steps = (
        (
            await tenant_session.execute(
                select(WorkflowStepRunModel).where(
                    WorkflowStepRunModel.tenant_id == seeded_ip_tenant,
                    WorkflowStepRunModel.run_id == wf_runs[0].id,
                )
            )
        )
        .scalars()
        .all()
    )

    out_records = (
        (
            await tenant_session.execute(
                select(OutboundRecordModel).where(
                    OutboundRecordModel.tenant_id == seeded_ip_tenant,
                    OutboundRecordModel.connection_id == dest_conn_id,
                )
            )
        )
        .scalars()
        .all()
    )

    trace_events = (
        (
            await tenant_session.execute(
                select(IpTraceEventModel).where(
                    IpTraceEventModel.tenant_id == seeded_ip_tenant,
                )
            )
        )
        .scalars()
        .all()
    )

    _assert_workflow_and_outbound_delivery_outcomes(
        workflow_runs=wf_runs,
        workflow_steps=wf_steps,
        outbound_records=out_records,
        trace_events=trace_events,
        dest_connection_id=dest_conn_id,
        meter_serial=meter_serial,
    )


@pytest.mark.asyncio
async def test_energy_l3_to_l5_idempotent_reconciliation_loop_suppression(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Verifies idempotency short-circuiting, step reconciliation, and return-leg loopback suppression."""
    admin_ctx = IdentityContext(
        subject="usr_energy_ops_idem",
        claims={},
        tenant_id=seeded_ip_tenant,
        authorized_tenants={seeded_ip_tenant},
        roles=(StandardRole.TENANT_ADMIN.value,),
    )
    active_identity: dict[str, IdentityContext] = {"current": admin_ctx}
    app = _build_test_app(
        global_session=global_session,
        transactional_router=transactional_router,
        active_identity=active_identity,
    )
    container = _configure_test_container(transactional_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        dest_conn_id = await _provision_erp_destination_connection(client, seeded_ip_tenant)

    deliver_use_case: DeliverOutboundRecordUseCase = container.session_scoped_outbound_delivery()
    http_step_handler: ExecuteHttpActionStepHandler = container.execute_http_action_step_handler()

    idem_key = "idem_energy_erp_reading_001"
    sample_payload = {
        "reading_id": "BILL-RDG-IDEM-001",
        "meter_serial": "MTR-ENERGY-9001",
        "kwh_delivered": 42.10,
        "reading_timestamp": "2026-11-12T14:00:00Z",
        "service_point_id": "SP-ENERGY-9001",
    }

    # 1. First Delivery Attempt -> DELIVERED (was_deduplicated=False)
    delivery_cmd = DeliverOutboundRecordCommand(
        tenant_id=seeded_ip_tenant,
        connection_id=dest_conn_id,
        stream_name="billing_readings",
        operation=HttpWriteOperation.CREATE.value,
        payload=sample_payload,
        record_id="BILL-RDG-IDEM-001",
        idempotency_key=idem_key,
        trace_id="ip_trc_idem_test_01",
    )
    first_res = await deliver_use_case.execute(delivery_cmd)
    assert first_res.is_ok
    first_resp: DeliverOutboundRecordResponse = first_res.unwrap()
    assert first_resp.status == OutboundDispatchStatus.DELIVERED
    assert first_resp.was_deduplicated is False
    assert first_resp.response_status_code == 200

    # 2. Second Delivery Attempt with Identical Idempotency Key -> Short-Circuits (was_deduplicated=True)
    dup_res = await deliver_use_case.execute(delivery_cmd)
    assert dup_res.is_ok
    dup_resp: DeliverOutboundRecordResponse = dup_res.unwrap()
    assert dup_resp.status == OutboundDispatchStatus.DELIVERED
    assert dup_resp.was_deduplicated is True
    assert dup_resp.outbound_record_id == first_resp.outbound_record_id

    # 3. Reconcile Phase: Step Handler Reconciles and Adopts Existing DELIVERED Outcome
    step_ctx = StepContext(
        tenant_id=seeded_ip_tenant,
        run_id="wfr_reconcile_test_01",
        step_run_id="wfs_reconcile_test_01",
        node_key="dispatch_erp_reading",
        idempotency_key=idem_key,
        retry_count=1,
        app_retry_count=1,
        internal_retry_count=0,
        deadline=datetime(2026, 11, 12, 18, 0, 0, tzinfo=UTC),
        trace_id="ip_trc_idem_test_01",
        correlation_id=None,
    )
    step_input = {
        "destination_connection_id": dest_conn_id,
        "destination_stream": "billing_readings",
        "operation": "CREATE",
        "record_id": "BILL-RDG-IDEM-001",
        "payload": sample_payload,
    }
    reconcile_res = await http_step_handler.reconcile(step_ctx, step_input)
    assert reconcile_res.is_ok
    outcome = reconcile_res.unwrap()
    assert outcome.found is True
    assert outcome.adopted_output is not None
    assert outcome.adopted_output["was_deduplicated"] is True
    assert outcome.adopted_output["status"] == OutboundDispatchStatus.DELIVERED.value

    # 4. Loop Suppression: Causation Depth >= DEFAULT_MAX_CAUSATION_DEPTH suppresses Return-Leg
    deep_cmd = DeliverOutboundRecordCommand(
        tenant_id=seeded_ip_tenant,
        connection_id=dest_conn_id,
        stream_name="billing_readings",
        operation=HttpWriteOperation.CREATE.value,
        payload={
            "reading_id": "BILL-RDG-LOOP-002",
            "meter_serial": "MTR-ENERGY-9002",
            "kwh_delivered": 15.0,
            "reading_timestamp": "2026-11-12T15:00:00Z",
            "service_point_id": "SP-ENERGY-9002",
        },
        record_id="BILL-RDG-LOOP-002",
        idempotency_key="idem_deep_loop_suppression",
        causation_depth=DEFAULT_MAX_CAUSATION_DEPTH,
        trace_id="ip_trc_loop_suppress_01",
    )
    deep_res = await deliver_use_case.execute(deep_cmd)
    assert deep_res.is_ok
    deep_resp = deep_res.unwrap()
    assert deep_resp.status == OutboundDispatchStatus.DELIVERED
    assert deep_resp.return_leg_inbound_record_id is None
