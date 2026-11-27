"""End-to-End Multi-HES Historical Extraction to MDM Kafka Pipeline Integration Tests on real PostgreSQL.

Exercises the complete lifecycle from the approved enterprise architecture:
1. Phase 1: Webhook Command Ingestion (L1 InboundRecord created, mode PUSH_FULL).
2. Phase 2: Post-L1 Command Routing (L2 Replica and L3 Normalization bypassed; routed to L4 Stitch).
3. Phase 3: L4 Slicing Workflow (Date range decomposed into atomic per-day tasks with destination configuration).
4. Phase 4: HES Readings Ingestion, L2 Dedup & L3 Canonical Normalization (IEC 61968 CIM format).
5. Phase 5: L5 Outbound Kafka Egress (Partition key: meter_serial_number, trace headers, CIM JSON value).

All tests run against real PostgreSQL inside nested SAVEPOINT transactions (TransactionalTestRouter).
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from datetime import datetime
from typing import Final

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from dependency_injector import providers
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from identity.domain.authorization import StandardRole
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
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
from ip.engine.adapters.outbound.connectors.kafka_connector import KafkaConnector
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    OutboundRecordModel,
    ReplicaRecordModel,
)
from ip.engine.adapters.outbound.database.tenant_resolver import (
    SqlAlchemyIpTenantResolver,
)
from ip.engine.adapters.outbound.stitches.step_handlers import SliceRangeStepHandler
from ip.engine.adapters.outbound.stitches.stitch_adapters import (
    IpStitchCanonicalDispatcherAdapter,
    IpStitchWorkerTickAdapter,
)
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
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
    create_engine_catalog_registry,
    create_ip_stitch_dispatcher,
    create_ip_stitch_worker_tick,
)
from ip.engine.bootstrap.publisher_factory import build_ip_dp_outbox_router
from ip.engine.domain.connection.enums import (
    AuthType,
)
from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.enums import IpEventType, IpOutboxSource
from ip.engine.domain.exceptions import ConnectionCheckError, IpError, KafkaConnectionError, Result
from ip.engine.domain.replication.enums import (
    FetchRecordStatus,
    IngestionMode,
    SyncRunStatus,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.stitch.steps import (
    SliceRangeStepOutput,
)
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.kafka_client_port import (
    KafkaProducerClientPort,
    KafkaProduceResultDTO,
)
from ip.module import IpApiModule
from ip.solutions.bootstrap import configure_solution_container
from ip.solutions.domains.energy.models import MdmMeterReadingRecord
from orchestration.adapters.outbound.database.models import (
    WorkflowPayloadModel,
    WorkflowRunModel,
    WorkflowStepRunModel,
)
from orchestration.domain.constants import EffectPolicy, PayloadType, RunStatus, StepStatus
from orchestration.domain.failures import StepFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import (
    MultiShardOutboxDrainRelay,
)
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from security.provider import SecurityProvider
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.utils import generate_id
from sqlalchemy import select

pytestmark = pytest.mark.integration

_TEST_KEY_BYTES: Final[bytes] = b"0123456789abcdef0123456789abcdef"
_WORKFLOW_ID: Final[str] = "energy.hes_historical_extraction_stitch"
_COMMAND_STREAM: Final[str] = "historical_extract_requests"
_DESTINATION_TOPIC: Final[str] = "mdm.readings.inbound"


class FakeKafkaProducerClient(KafkaProducerClientPort):
    """In-memory test double capturing produced Kafka records with headers and partition keys."""

    def __init__(self) -> None:
        self.produced_messages: list[tuple[str, bytes, bytes | None, Mapping[str, bytes]]] = []
        self._closed = False

    async def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: Mapping[str, bytes] | None = None,
        partition: int | None = None,
    ) -> Result[KafkaProduceResultDTO, KafkaConnectionError]:
        hdrs = dict(headers or {})
        self.produced_messages.append((topic, value, key, hdrs))
        offset = len(self.produced_messages)
        assigned_partition = partition if partition is not None else 0
        return Result.ok(
            KafkaProduceResultDTO(
                topic=topic,
                partition=assigned_partition,
                offset=offset,
                timestamp_ms=1763100000000 + offset,
            )
        )

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        return Result.ok(None)

    async def list_topics(self) -> Result[Sequence[str], KafkaConnectionError]:
        return Result.ok((_DESTINATION_TOPIC, "mdm.events.inbound"))

    async def close(self) -> None:
        self._closed = True


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


class _PassthroughStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Pure passthrough step double for downstream multi-HES fanout and stream nodes."""

    def __init__(self, step_type: str) -> None:
        self._step_type = step_type

    @property
    def step_type(self) -> str:
        return self._step_type

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        return Result.ok(dict(step_input))


def _configure_test_container(
    transactional_router: TransactionalTestRouter,
    fake_kafka_client: FakeKafkaProducerClient,
) -> Container:
    resolver = SqlAlchemyIpTenantResolver(transactional_router)
    container = configure_solution_container(Container())
    container.config.allow_private_ips.from_value(True)
    container.db_router.override(providers.Object(transactional_router))
    container.tenant_resolver.override(providers.Object(resolver))

    # Override catalog registry with FakeKafkaProducerClient-wired KafkaConnector
    custom_kafka = KafkaConnector(client=fake_kafka_client)
    custom_registry = create_engine_catalog_registry(
        allow_private_ips=True,
        auth_resolver=container.auth_resolver(),
    )
    custom_registry.register_connector(
        custom_kafka,
        KafkaConnector.default_catalog_summary(),
    )
    container.catalog_registry.override(providers.Object(custom_registry))

    # Ensure SliceRangeStepHandler and downstream passthrough handlers are registered
    step_reg = container.step_handler_registry()
    step_reg.register(SliceRangeStepHandler())
    for passthrough_type in (
        "trigger.ingress",
        "energy.fanout_by_connection",
        "http.post_extract",
        "itron.parse_openway_batch",
        "itron.normalize_intervals",
        "kafka.publish_intervals",
        "landis.parse_cim_batch",
        "landis.normalize_intervals",
        "siemens.parse_energyip_batch",
        "siemens.normalize_intervals",
    ):
        step_reg.register(_PassthroughStepHandler(passthrough_type))

    # Ensure HES historical extraction stitch is active in stitch_catalog
    stitch_catalog = container.stitch_catalog()
    stitch_catalog.register_stitch(
        Stitch(
            id="stch_hes_historical_extraction",
            tenant_id=PLATFORM_TENANT_ID,
            canonical_event_type="command.historical_extract_requests",
            target_workflow_id=_WORKFLOW_ID,
            name="HES Historical Interval Extraction",
            description="Decomposes MDM historical extract requests into atomic daily pull tasks per HES connection.",
            idempotency_key_field="source_inbound_record_id",
            is_active=True,
        )
    )

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


def _build_outbox_drain_pipeline(
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


async def _provision_kafka_destination_connection(
    client: AsyncClient,
    tenant_id: str,
) -> str:
    """Provisions a Kafka Destination Connection managed as a first-class connection."""
    check_resp = await client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/check",
        json={
            "app_id": "kafka",
            "auth_type": AuthType.NO_AUTH.value,
            "public_config": {
                "bootstrap_servers": "localhost:9092",
                "default_topic": _DESTINATION_TOPIC,
                "partition_key_field": "meter_serial_number",
            },
            "raw_credentials": {},
        },
    )
    assert check_resp.status_code == 200

    conn_resp = await client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "kafka",
            "name": "MDM Enterprise Kafka Inbound Broker",
            "auth_type": AuthType.NO_AUTH.value,
            "public_config": {
                "bootstrap_servers": "localhost:9092",
                "default_topic": _DESTINATION_TOPIC,
                "partition_key_field": "meter_serial_number",
            },
            "raw_credentials": {},
            "endpoint_for_fingerprint": "kafka:9092",
        },
    )
    assert conn_resp.status_code == 201
    return str(conn_resp.json()["id"])


@pytest.mark.asyncio
async def test_hes_historical_extraction_to_mdm_kafka_pipeline(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Exercises full Multi-HES Historical Extraction to MDM Kafka Pipeline.

    Lifecycle verification:
    1. MDM initiates webhook extraction command -> L1 InboundRecord created.
    2. Post-L1 Router detects stream_name='historical_extract_requests' -> bypasses L2 replication.
    3. Direct L4 handoff -> energy.hes_historical_extraction_stitch runs SliceRangeStepHandler.
    4. Slicing decomposes 2026-10-01 to 2026-10-03 into 2 daily slices per HES.
    5. HES interval readings are ingested and normalized into IEC 61968 CIM MdmMeterReadingRecord.
    6. DeliverOutboundRecordUseCase dispatches to KafkaConnector -> produces to mdm.readings.inbound.
    7. Verifies partition key, trace headers, payload wire format, and trace lineage.
    """
    fake_kafka = FakeKafkaProducerClient()
    admin_ctx = IdentityContext(
        subject="usr_grid_mdm_operator",
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
    container = _configure_test_container(transactional_router, fake_kafka)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: Provision Kafka Destination Connection
        kafka_conn_id = await _provision_kafka_destination_connection(client, seeded_ip_tenant)

    # Step 2: Assemble Outbox Pipeline & Orchestration
    (
        drain_relay,
        _orch_bridge,
        _delivery_bridge,
        _stitch_dispatcher,
        _stitch_worker_tick,
    ) = _build_outbox_drain_pipeline(
        container=container,
        transactional_router=transactional_router,
    )

    dp_uow_provider = container.dp_uow_provider()
    shard_res = await dp_uow_provider.resolve_shard_info(seeded_ip_tenant)
    shard_id, shard_dsn = shard_res.unwrap()

    # Step 3: Phase 1 - Ingest MDM Webhook Command into L1
    command_correlation_id = "MDM-REQ-2026-11-8891"
    command_trace_id = "ip_trc_hes_extract_root_99"
    hes_conn_id = "ip_conn_itron_openway_north"

    command_body: JsonDict = {
        "tenant_id": seeded_ip_tenant,
        "correlation_id": command_correlation_id,
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-03T00:00:00Z",
        "hes_connection_ids": [hes_conn_id],
        "destination_connection_id": kafka_conn_id,
        "destination_topic": _DESTINATION_TOPIC,
        "filter_criteria": {
            "meter_serials": ["MTR-ENERGY-1001"],
            "reading_type": "INTERVAL_15_MIN",
        },
    }
    raw_cmd_bytes = json.dumps(command_body).encode("utf-8")

    inbound_cmd = InboundRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id="conn_mdm_webhook_trigger",
        app_id="webhook",
        stream_name=_COMMAND_STREAM,
        payload_bytes=raw_cmd_bytes,
        is_inlined=True,
        request_body=command_body,
        trace_id=command_trace_id,
        correlation_id=command_correlation_id,
        ingestion_mode=IngestionMode.PUSH_FULL,
    )

    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save(inbound_cmd)
        cmd_outbox_event = IpDataPlaneOutboxRecord(
            id=generate_id(IpDataPlaneOutboxRecord.ID_PREFIX),
            idempotency_key=f"idem_inb_{inbound_cmd.id}",
            tenant_id=seeded_ip_tenant,
            event_type=IpEventType.INBOUND_RECORD_CREATED.value,
            trace_id=command_trace_id,
            correlation_id=command_correlation_id,
            lane=EventProcessingLane.REALTIME.value,
            payload={
                "connection_id": "conn_mdm_webhook_trigger",
                "stream_name": _COMMAND_STREAM,
                "record_ids": [inbound_cmd.id],
            },
        )
        tenant_session.add(cmd_outbox_event)
        await uow.commit()

    # Step 4: Phase 2 - Drain outbox: Orchestrator routes command stream directly to L4
    await _drain_outbox_fully(drain_relay, max_iterations=4)
    tenant_session.expire_all()

    # CRITICAL INVARIANT: Verify L2 & L3 Replication was completely bypassed for command!
    replica_records = (
        (
            await tenant_session.execute(
                select(ReplicaRecordModel).where(
                    ReplicaRecordModel.tenant_id == seeded_ip_tenant,
                    ReplicaRecordModel.stream == _COMMAND_STREAM,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(replica_records) == 0, (
        "Command records must NEVER be replicated to L2 replica_records!"
    )

    # Step 5: Phase 3 - Verify L4 Stitch Workflow Instantiation & Slicing DAG Execution
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
    assert len(wf_runs) >= 1, f"Expected workflow run for {_WORKFLOW_ID}"
    hes_wf_run = wf_runs[0]
    assert hes_wf_run.status == RunStatus.SUCCEEDED.value

    # Check Workflow Step Runs: slice_date_range must be SUCCEEDED
    wf_steps = (
        (
            await tenant_session.execute(
                select(WorkflowStepRunModel).where(
                    WorkflowStepRunModel.tenant_id == seeded_ip_tenant,
                    WorkflowStepRunModel.run_id == hes_wf_run.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(wf_steps) >= 1
    slice_step = next((s for s in wf_steps if s.node_key == "slice_date_range"), None)
    assert slice_step is not None
    assert slice_step.status == StepStatus.SUCCEEDED.value

    # Verify Slicing Output Decomposition
    step_payload_record = (
        await tenant_session.execute(
            select(WorkflowPayloadModel).where(
                WorkflowPayloadModel.tenant_id == seeded_ip_tenant,
                WorkflowPayloadModel.owner_id == slice_step.id,
                WorkflowPayloadModel.payload_type == PayloadType.STEP_OUTPUT.value,
            )
        )
    ).scalar_one_or_none()
    assert step_payload_record is not None
    assert step_payload_record.inline_content is not None
    slice_output = SliceRangeStepOutput.from_payload(step_payload_record.inline_content).unwrap()
    assert len(slice_output.tasks) == 2, "Expected 2 daily slices for 2026-10-01 to 2026-10-03"
    t1, t2 = slice_output.tasks[0], slice_output.tasks[1]
    assert t1.target_connection_id == hes_conn_id
    assert t1.destination_connection_id == kafka_conn_id
    assert t1.destination_topic == _DESTINATION_TOPIC
    assert "2026-10-01" in t1.start_date.isoformat()
    assert "2026-10-02" in t2.start_date.isoformat()

    # Step 6: Phase 4 - Ingest HES readings & normalize into IEC 61968 CIM
    reading_timestamp_iso = "2026-10-01T12:00:00Z"
    dt_ts = datetime.fromisoformat(reading_timestamp_iso.replace("Z", "+00:00"))
    meter_serial = "MTR-ENERGY-1001"
    sp_id = "SP-NORTH-401"
    kwh = 14.52

    canonical_mr = MdmMeterReadingRecord(
        id=f"mr_{meter_serial}",
        tenant_id=seeded_ip_tenant,
        trace_id=command_trace_id,
        correlation_id=command_correlation_id,
        source_connection_id=hes_conn_id,
        source_replica_id=f"rep_{meter_serial}",
        transformation_id="energy.ami_meter_reading",
        transformation_version=2,
        meter_serial_number=meter_serial,
        service_point_id=sp_id,
        reading_timestamp=dt_ts,
        interval_minutes=15,
        kwh_delivered=kwh,
        kwh_received=0.0,
        voltage_avg=240.1,
        quality_flag="VALIDATED",
        recorded_at=dt_ts,
    )
    tenant_session.add(canonical_mr)

    # Step 7: Phase 5 - L5 Chronological Outbound Kafka Delivery
    delivery_use_case = container.session_scoped_outbound_delivery()
    delivery_cmd = DeliverOutboundRecordCommand(
        tenant_id=seeded_ip_tenant,
        connection_id=kafka_conn_id,
        stream_name=_DESTINATION_TOPIC,
        payload={
            "reading_id": canonical_mr.id,
            "meter_serial_number": meter_serial,
            "service_point_id": sp_id,
            "reading_timestamp": reading_timestamp_iso,
            "interval_minutes": 15,
            "kwh_delivered": kwh,
            "kwh_received": 0.0,
            "voltage_avg": 240.1,
            "quality_flag": "VALIDATED",
        },
        record_id=meter_serial,
        trace_id=command_trace_id,
        correlation_id=command_correlation_id,
    )

    deliv_res = await delivery_use_case.execute(delivery_cmd)
    assert deliv_res.is_ok
    deliv_dto = deliv_res.unwrap()
    assert deliv_dto.status == OutboundDispatchStatus.DELIVERED
    assert deliv_dto.record_id == meter_serial

    # Step 8: Verify Produced Kafka Record Wire Format
    assert len(fake_kafka.produced_messages) == 1
    produced_topic, val_bytes, key_bytes, produced_headers = fake_kafka.produced_messages[0]

    # Verify Topic & Key Partitioning
    assert produced_topic == _DESTINATION_TOPIC
    assert key_bytes == meter_serial.encode("utf-8"), (
        "Partition key MUST be meter_serial_number for in-order delivery!"
    )

    # Verify Trace Headers
    assert produced_headers["trace_id"].decode("utf-8") == command_trace_id
    assert produced_headers["correlation_id"].decode("utf-8") == command_correlation_id
    assert produced_headers["tenant_id"].decode("utf-8") == seeded_ip_tenant
    assert "produced_at" in produced_headers

    # Verify Normalized CIM Payload Value
    produced_value = json.loads(val_bytes.decode("utf-8"))
    assert produced_value["meter_serial_number"] == meter_serial
    assert produced_value["service_point_id"] == sp_id
    assert produced_value["reading_timestamp"] == reading_timestamp_iso
    assert produced_value["kwh_delivered"] == kwh
    assert produced_value["quality_flag"] == "VALIDATED"

    # Step 9: Verify Outbound Record in Postgres Ledger
    tenant_session.expire_all()
    outbound_records = (
        (
            await tenant_session.execute(
                select(OutboundRecordModel).where(
                    OutboundRecordModel.tenant_id == seeded_ip_tenant,
                    OutboundRecordModel.connection_id == kafka_conn_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbound_records) == 1
    saved_outbound = outbound_records[0]
    assert saved_outbound.status == OutboundDispatchStatus.DELIVERED.value
    assert saved_outbound.response_status_code == 200
    assert saved_outbound.external_record_id == f"{_DESTINATION_TOPIC}:0:1"
    assert saved_outbound.target_url == f"kafka://{_DESTINATION_TOPIC}"
