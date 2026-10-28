"""End-to-End Transactional Outbox & Worker Pipeline Integration Tests on real PostgreSQL.

Exercises the complete 5-Stage SEDA Pipeline (L1 -> Outbox Drain -> L2 -> Outbox Drain ->
L3 -> Outbox Drain -> L4 -> Outbox Drain -> L5 + Trace Waterfall & Consumer Idempotency)
for both:
  1. Realtime Webhook (N=1 on EventProcessingLane.REALTIME)
  2. Bulk Meter Sync Batch (N=4 on EventProcessingLane.BULK)
inside SAVEPOINT-isolated transactions (`global_session`, `tenant_session`, `transactional_router`).
"""

from __future__ import annotations

import json

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession
from ip.engine.adapters.inbound.workers import (
    IpDeliveryRouteRegistry,
    IpFetchRecordExecutorPort,
    IpNormalizeReplicaExecutorPort,
    IpOrchestratorRouteRegistry,
    IpOutboundDeliveryExecutorPort,
    IpRunSyncExecutorPort,
    IpStitchCanonicalDispatcherPort,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpProcessedEventModel,
    IpTraceEventModel,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import IpTenantUoWProvider
from ip.engine.adapters.outbound.pubsub.publisher_factory import (
    build_ip_dp_outbox_router,
)
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordResponse,
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
    BackfillStreamNormalizationUseCase,
)
from ip.engine.application.use_cases.normalization.bind_stream_transformation_use_case import (
    BindStreamTransformationCommand,
    BindStreamTransformationUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.domain.enums import (
    AuthType,
    CursorKind,
    HttpWriteOperation,
    IngestionMode,
    IpOutboxSource,
    OutboundDispatchStatus,
    SyncMode,
    SyncRunKind,
    SyncRunStatus,
    TransformationMode,
)
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.domain.normalization import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    ReplicaSnapshot,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.services.canonical_entity_registry import CanonicalEntityRegistry
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.domain.services.default_normalization_error_policy import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.services.transformer_registry import InMemoryTransformerRegistry
from ip.engine.ports.outbound.canonical_writer_port import CanonicalWriterPort
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from orchestration.domain.exceptions import Result as WorkflowResult
from orchestration.domain.exceptions import WorkflowError
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import (
    MultiShardOutboxDrainRelay,
)
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane
from sqlalchemy import select

pytestmark = pytest.mark.integration


class _InMemoryQueueBridgePublisher(OutboxPublisherPort):
    """Bridges OutboxPublisherPort directly into an EventEnvelopeDispatcher while recording lanes."""

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


class _PipelineMeterTransformer(TransformerPort):
    """Pure L3 Transformer transforming meter_reads replica snapshots into energy.meter.v1 drafts."""

    @property
    def transformation_id(self) -> str:
        return "itron_meter_to_energy_meter"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("energy.meter.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        meter_id = str(replica.data.get("meter_id", replica.record_key))
        raw_kwh = replica.data.get("kwh", 0.0)
        kwh = float(raw_kwh) if isinstance(raw_kwh, (int, float)) else 0.0
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="energy.meter.v1",
                    source_id=meter_id,
                    fields={
                        "meter_serial": meter_id,
                        "kwh": kwh,
                        "status": "ACTIVE",
                    },
                ),
            )
        )


class _PipelineCanonicalWriter(CanonicalWriterPort):
    """Test harness canonical writer recording normalized canonical rows."""

    def __init__(self) -> None:
        self.rows: dict[str, JsonDict] = {}

    @property
    def canonical_type(self) -> str:
        return "energy.meter.v1"

    async def upsert(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        transformation_id: str,
        transformation_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        self.rows[source_id] = dict(fields)

    async def soft_delete(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        self.rows.pop(source_id, None)

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        if source_id in self.rows:
            return f"canon_meter_{source_id}"
        return None

    async def resolve_reference(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        field_name: str,
        target_id: str,
        trace_id: str,
    ) -> None:
        if source_id in self.rows:
            self.rows[source_id][field_name] = target_id


class _PipelineNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    """Wraps NormalizeReplicaRecordUseCase with the test's Control Plane UoW."""

    def __init__(self, use_case: NormalizeReplicaRecordUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        return await self._use_case.execute(command)


class _PipelineStitchDispatcher(IpStitchCanonicalDispatcherPort):
    """L4 Stitch dispatcher that stages an L5 OutboundRecord in the Data Plane outbox for each canonical event."""

    def __init__(
        self,
        dp_uow_provider: IpTenantUoWProvider,
        connection_id: str,
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._connection_id = connection_id
        self.dispatched_commands: list[DispatchCanonicalEventToStitchesCommand] = []

    async def execute(
        self, command: DispatchCanonicalEventToStitchesCommand
    ) -> WorkflowResult[DispatchCanonicalEventResultDTO, WorkflowError]:
        self.dispatched_commands.append(command)
        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        shard_id, shard_dsn = shard_res.unwrap()
        body: JsonDict = dict(command.payload)
        raw_bytes = json.dumps(body).encode("utf-8")
        out_rec = OutboundRecord.create_pending(
            tenant_id=command.tenant_id,
            connection_id=self._connection_id,
            app_id="itron",
            stream_name="erp_meters",
            target_url="https://erp.example.com/api/meters",
            http_method="POST",
            payload_bytes=raw_bytes,
            is_inlined=True,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            operation=HttpWriteOperation.UPSERT.value,
            idempotency_key=f"idem_l5_{command.event_id}",
            external_record_id=str(command.payload.get("source_id", command.event_id)),
            request_body=body,
        )
        async with self._dp_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            await uow.outbound_records.save(out_rec)
            await uow.commit()
        return WorkflowResult.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=(f"wf_{command.event_id}",),
                deduplicated_run_ids=(),
                signalled_step_ids=(),
            )
        )


class _PipelineOutboundDeliveryExecutor(IpOutboundDeliveryExecutorPort):
    """L5 Outbound Delivery executor that marks staged OutboundRecords as DELIVERED in the DB."""

    def __init__(self, dp_uow_provider: IpTenantUoWProvider) -> None:
        self._dp_uow_provider = dp_uow_provider
        self.delivered_commands: list[DeliverOutboundRecordCommand] = []

    async def execute(
        self, command: DeliverOutboundRecordCommand
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        self.delivered_commands.append(command)
        if command.idempotency_key:
            shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
            shard_id, shard_dsn = shard_res.unwrap()
            async with self._dp_uow_provider.get_data_plane_uow(
                command.tenant_id, shard_id, shard_dsn
            ) as uow:
                staged = await uow.outbound_records.get_by_idempotency_key(
                    command.tenant_id,
                    command.connection_id,
                    command.idempotency_key,
                )
                if staged is not None:
                    staged.mark_delivered(
                        response_status_code=200,
                        response_body={"status": "OK", "id": command.record_id},
                        duration_ms=11,
                        external_record_id=command.record_id,
                    )
                    await uow.outbound_records.save(staged)
                    await uow.commit()
        return Result.ok(
            DeliverOutboundRecordResponse(
                outbound_record_id=command.idempotency_key or "out_1",
                status=OutboundDispatchStatus.DELIVERED,
                trace_id=command.trace_id or "tr_1",
                idempotency_key=command.idempotency_key or "idem_1",
                record_id=command.record_id or "rec_1",
                destination_id=f"erp_{command.record_id}",
                response_status_code=200,
                duration_ms=11,
            )
        )


class _NoopFetchExecutor(IpFetchRecordExecutorPort):
    async def execute(self, command: FetchRecordCommand) -> FetchRecordResultDTO:
        return FetchRecordResultDTO(
            status="FETCHED",
            trace_id=command.trace_id or "tr",
            record_id=command.record_id,
        )


class _NoopRunSyncExecutor(IpRunSyncExecutorPort):
    async def execute(self, command: RunSyncCommand) -> RunSyncResultDTO:
        return RunSyncResultDTO(
            run_id="run_1",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            kind=SyncRunKind.INCREMENTAL.value,
            status=SyncRunStatus.SUCCEEDED.value,
            pages_synced=1,
            records_synced=1,
            bytes_synced=64,
        )


@pytest.mark.asyncio
async def test_end_to_end_pipeline_realtime_and_bulk_across_all_5_layers(
    seeded_ip_tenant: str,
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify both Realtime (N=1) and Bulk (N=4) flow L1 -> L2 -> L3 -> L4 -> L5 via Outbox Drain."""
    cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    tenant_resolver = IpTenantResolver(db_router=transactional_router)
    dp_uow_provider = IpTenantUoWProvider(
        resolver=tenant_resolver,
        db_router=transactional_router,
    )

    # 1. Seed Control Plane Connection & Transformation for stream 'meter_reads'
    connection = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron",
        name="Itron Utility MDM",
        auth_type=AuthType.API_KEY,
        public_config={"base_url": "https://itron.example.com"},
        encrypted_credentials=b"enc_secret",
        endpoint_for_fingerprint="https://itron.example.com",
    )
    connection.activate()
    save_conn_res = await cp_uow.connections.save(connection)
    assert save_conn_res.is_ok

    entity_registry = CanonicalEntityRegistry()
    entity_registry.register(
        CanonicalEntityDefinition(
            canonical_type="energy.meter.v1",
            schema_version=1,
        )
    )
    transformer_registry = InMemoryTransformerRegistry()
    transformer_registry.register(_PipelineMeterTransformer())
    canonical_writer = _PipelineCanonicalWriter()
    writer_registry: InMemoryCanonicalWriterRegistry[CanonicalWriterPort] = (
        InMemoryCanonicalWriterRegistry()
    )
    writer_registry.register(canonical_writer)

    bind_uc = BindStreamTransformationUseCase(
        control_plane_uow=cp_uow,
        transformer_registry=transformer_registry,
    )
    bind_res = await bind_uc.execute(
        BindStreamTransformationCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=connection.id,
            stream="meter_reads",
            transformation_id="itron_meter_to_energy_meter",
            transformation_version=1,
            mode=TransformationMode.ACTIVE,
        )
    )
    assert bind_res.is_ok

    normalize_uc = NormalizeReplicaRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        transformer_registry=transformer_registry,
        writer_registry=writer_registry,
        entity_registry=entity_registry,
        error_policy=DefaultNormalizationErrorPolicy(),
    )
    backfill_uc = BackfillStreamNormalizationUseCase(
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_uc,
    )
    stitch_dispatcher = _PipelineStitchDispatcher(dp_uow_provider, connection.id)
    delivery_executor = _PipelineOutboundDeliveryExecutor(dp_uow_provider)

    # 2. Wire Orchestrator & Delivery Route Registries and Outbox Router (Realtime + Bulk lanes)
    orch_dispatcher = EventEnvelopeDispatcher()
    deliv_dispatcher = EventEnvelopeDispatcher()

    stream_def = StreamDefinition(
        stream="meter_reads",
        primary_key=(("meter_id",),),
        cursor_field=("read_at",),
        cursor_kind=CursorKind.STRING,
        sync_mode=SyncMode.INCREMENTAL,
    )
    orch_registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        normalize_use_case=_PipelineNormalizeExecutor(normalize_uc),
        backfill_use_case=backfill_uc,
        stitch_dispatcher=stitch_dispatcher,
        stream_definition_resolver=lambda t, c, s: stream_def,
        max_chunk_concurrency=4,
    )
    orch_registry.register_routes(orch_dispatcher)

    deliv_registry = IpDeliveryRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        deliver_outbound_use_case=delivery_executor,
        fetch_record_use_case=_NoopFetchExecutor(),
        run_sync_use_case=_NoopRunSyncExecutor(),
        max_chunk_concurrency=4,
    )
    deliv_registry.register_routes(deliv_dispatcher)

    orch_rt_bridge = _InMemoryQueueBridgePublisher(orch_dispatcher)
    orch_bulk_bridge = _InMemoryQueueBridgePublisher(orch_dispatcher)
    deliv_rt_bridge = _InMemoryQueueBridgePublisher(deliv_dispatcher)
    deliv_bulk_bridge = _InMemoryQueueBridgePublisher(deliv_dispatcher)
    noop_bridge = _InMemoryQueueBridgePublisher(EventEnvelopeDispatcher())

    dp_router = build_ip_dp_outbox_router(
        orchestrator_realtime_publisher=orch_rt_bridge,
        orchestrator_bulk_publisher=orch_bulk_bridge,
        delivery_realtime_publisher=deliv_rt_bridge,
        delivery_bulk_publisher=deliv_bulk_bridge,
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

    # ==========================================================================
    # SCENARIO A: Realtime Single-Record Webhook (N=1, Lane=REALTIME)
    # ==========================================================================
    shard_res = await dp_uow_provider.resolve_shard_info(seeded_ip_tenant)
    shard_id, shard_dsn = shard_res.unwrap()

    rt_payload: JsonDict = {
        "meter_id": "MTR-RT-01",
        "kwh": 42.5,
        "read_at": "2026-10-27T10:00:00Z",
    }
    rt_record = InboundRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=connection.id,
        app_id="itron",
        stream_name="meter_reads",
        payload_bytes=json.dumps(rt_payload).encode("utf-8"),
        is_inlined=True,
        request_body=rt_payload,
        trace_id="ip_trc_rt_001",
        correlation_id="MTR-RT-01",
        ingestion_mode=IngestionMode.PUSH_FULL,
    )
    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save(rt_record)
        await uow.commit()

    # Drain until all cascading stages (L1 -> L2 -> L3 -> L4 -> L5) settle
    for _ in range(6):
        drained = await drain_relay.drain_all_shards_once()
        if drained == 0:
            break

    # Verify Realtime record reached L3 Canonical Writer and L5 Outbound Delivery
    assert "MTR-RT-01" in canonical_writer.rows
    assert canonical_writer.rows["MTR-RT-01"]["kwh"] == 42.5
    assert any(c.record_id == "MTR-RT-01" for c in delivery_executor.delivered_commands)
    assert len(orch_rt_bridge.published_envelopes) >= 3  # L1->L2, L2->L3, L3->L4 on REALTIME lane
    assert len(deliv_rt_bridge.published_envelopes) >= 1  # L4->L5 on REALTIME lane

    # ==========================================================================
    # SCENARIO B: Bulk Multi-Record Batch (N=4 records in 1 L1 batch)
    # ==========================================================================
    bulk_records_payload: JsonDict = {
        "records": [
            {"meter_id": "MTR-BLK-01", "kwh": 100.0, "read_at": "2026-10-27T11:00:00Z"},
            {"meter_id": "MTR-BLK-02", "kwh": 200.0, "read_at": "2026-10-27T11:00:00Z"},
            {"meter_id": "MTR-BLK-03", "kwh": 300.0, "read_at": "2026-10-27T11:00:00Z"},
            {"meter_id": "MTR-BLK-04", "kwh": 400.0, "read_at": "2026-10-27T11:00:00Z"},
        ]
    }
    stream_def_bulk = StreamDefinition(
        stream="meter_reads",
        record_path=("records",),
        primary_key=(("meter_id",),),
        cursor_field=("read_at",),
        cursor_kind=CursorKind.STRING,
        sync_mode=SyncMode.INCREMENTAL,
    )
    orch_registry._stream_definition_resolver = lambda t, c, s: stream_def_bulk

    bulk_inb = InboundRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=connection.id,
        app_id="itron",
        stream_name="meter_reads",
        payload_bytes=json.dumps(bulk_records_payload).encode("utf-8"),
        is_inlined=True,
        request_body=bulk_records_payload,
        trace_id="ip_trc_bulk_001",
        correlation_id="BATCH-BLK-01",
        ingestion_mode=IngestionMode.PULL_INCREMENTAL,
    )
    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save(bulk_inb)
        await uow.commit()

    for _ in range(6):
        drained = await drain_relay.drain_all_shards_once()
        if drained == 0:
            break

    # Verify all 4 Bulk meter records were extracted, normalized, stitched, and delivered!
    for idx in range(1, 5):
        meter_key = f"MTR-BLK-0{idx}"
        assert meter_key in canonical_writer.rows
        assert canonical_writer.rows[meter_key]["kwh"] == float(idx * 100)
        assert any(c.record_id == meter_key for c in delivery_executor.delivered_commands)

    # Verify L2 emitted a BULK chunk-pointer event (`len(record_ids) == 4`, `lane == BULK`)
    # which was routed to `orch_bulk_bridge`!
    rep_bulk_envelopes = [
        env
        for env in orch_bulk_bridge.published_envelopes
        if env.event_type == "ip.replica_record.changed"
    ]
    assert len(rep_bulk_envelopes) == 1
    rep_bulk_env = rep_bulk_envelopes[0]
    assert rep_bulk_env.lane is EventProcessingLane.BULK
    raw_bulk_ids = rep_bulk_env.payload.get("record_ids")
    assert isinstance(raw_bulk_ids, list) and len(raw_bulk_ids) == 4

    # Verify trace events and consumer idempotency rows were persisted in the tenant shard
    async for verify_session in transactional_router.get_tenant_session(
        seeded_ip_tenant, shard_id, shard_dsn
    ):
        trace_rows = (
            (
                await verify_session.execute(
                    select(IpTraceEventModel).where(
                        IpTraceEventModel.tenant_id == seeded_ip_tenant,
                        IpTraceEventModel.trace_id == "ip_trc_rt_001",
                    )
                )
            )
            .scalars()
            .all()
        )
        event_types_seen = {r.event_type for r in trace_rows}
        assert any(et.startswith("L1_") for et in event_types_seen)
        assert any(et.startswith("L2_") for et in event_types_seen)
        assert any(et.startswith("L3_") for et in event_types_seen)
        assert any(et.startswith("L5_") for et in event_types_seen)

        processed_rows = (
            (
                await verify_session.execute(
                    select(IpProcessedEventModel).where(
                        IpProcessedEventModel.tenant_id == seeded_ip_tenant
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(processed_rows) >= 4
