"""End-to-End Transactional Outbox & Worker Pipeline Integration Tests on real PostgreSQL.

Exercises the Gear-1 2-Queue Data Plane Pipeline:
  Stage 1 (L1): `InboundRecord` / `create_range_batch` -> `ip_outbox` (`ip.inbound_record.created`)
  Stage 2 (L2->L3): Fused `ProcessInboundRangeUseCase` in a single ACID transaction (zero internal hops)
  Stage 3 (L4): In-memory Stitch evaluation -> `OutboundRecord(PENDING)` -> `ip_outbox` (`ip.outbound_record.created`)
  Stage 4 (L5): `ip-delivery-worker` `DELIVERED` + Return-Leg `ResponseEventEnvelope` loopback (`causation_depth=1`)
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
    IpProcessInboundRangeExecutorPort,
    IpRunSyncExecutorPort,
    IpStitchCanonicalDispatcherPort,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpProcessedEventModel,
    IpTraceEventModel,
)
from ip.engine.adapters.outbound.database.tenant_resolver import SqlAlchemyIpTenantResolver
from ip.engine.adapters.outbound.database.tenant_uow_provider import (
    SqlAlchemyIpTenantUoWProvider,
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
from ip.engine.application.use_cases.normalization.process_inbound_range_use_case import (
    ProcessInboundRangeCommand,
    ProcessInboundRangeResultDTO,
    ProcessInboundRangeUseCase,
)
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
)
from ip.engine.bootstrap.container import (
    create_ip_control_plane_uow,
    create_ip_tenant_uow_provider,
)
from ip.engine.bootstrap.publisher_factory import (
    build_ip_dp_outbox_router,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundDispatchStatus,
)
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.dispatch.response_envelope import ResponseEventEnvelope
from ip.engine.domain.enums import IpEventType, IpOutboxSource
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.normalization.enums import TransformationMode
from ip.engine.domain.normalization.policies import (
    DefaultNormalizationErrorPolicy,
)
from ip.engine.domain.normalization.registries import (
    CanonicalEntityRegistry,
    CanonicalWriterRegistry,
    TransformerRegistry,
)
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    ReplicaSnapshot,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.replication.enums import (
    CursorKind,
    IngestionMode,
    SyncMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.replication.inbound_record import (
    InboundBatchItemSpec,
    InboundRecord,
)
from ip.engine.domain.replication.stream_definition import StreamDefinition
from ip.engine.domain.trace.enums import IpTraceEventType
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


class _PipelineRecordTransformer(TransformerPort):
    """Pure L3 Transformer transforming records_alpha replica snapshots into canonical.record_alpha.v1 drafts."""

    @property
    def transformation_id(self) -> str:
        return "acme_record_to_canonical_alpha"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return ("canonical.record_alpha.v1",)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        _ = context
        record_id = str(replica.data.get("record_id", replica.record_key))
        raw_amount = replica.data.get("amount", 0.0)
        amount = float(raw_amount) if isinstance(raw_amount, (int, float)) else 0.0
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type="canonical.record_alpha.v1",
                    source_id=record_id,
                    fields={
                        "external_id": record_id,
                        "amount": amount,
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
        return "canonical.record_alpha.v1"

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
            return f"canon_alpha_{source_id}"
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


class _PipelineRangeExecutor(IpProcessInboundRangeExecutorPort):
    """Wraps ProcessInboundRangeUseCase with the test's Control Plane UoW."""

    def __init__(self, use_case: ProcessInboundRangeUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self, command: ProcessInboundRangeCommand
    ) -> Result[ProcessInboundRangeResultDTO, IpError]:
        return await self._use_case.execute(command)


class _PipelineStitchDispatcher(IpStitchCanonicalDispatcherPort):
    """L4 Stitch dispatcher that stages an L5 OutboundRecord in the Data Plane outbox for each canonical event."""

    def __init__(
        self,
        dp_uow_provider: SqlAlchemyIpTenantUoWProvider,
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
        raw_depth = command.payload.get("causation_depth", 0)
        causation_depth = int(raw_depth) if isinstance(raw_depth, int) else 0
        out_rec = OutboundRecord.create_pending(
            tenant_id=command.tenant_id,
            connection_id=self._connection_id,
            app_id="acme_source",
            stream_name="sink_records",
            target_url="https://sink.example.com/api/records",
            http_method="POST",
            payload_bytes=raw_bytes,
            is_inlined=True,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            operation=HttpWriteOperation.UPSERT.value,
            idempotency_key=f"idem_l5_{command.event_id}",
            external_record_id=str(command.payload.get("source_id", command.event_id)),
            request_body=body,
            causation_depth=causation_depth,
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
    """L5 Outbound Delivery executor that marks staged OutboundRecords DELIVERED and loops back Return-Leg."""

    def __init__(
        self,
        dp_uow_provider: SqlAlchemyIpTenantUoWProvider,
        *,
        max_causation_depth: int = 3,
    ) -> None:
        self._dp_uow_provider = dp_uow_provider
        self._max_causation_depth = max_causation_depth
        self.delivered_commands: list[DeliverOutboundRecordCommand] = []

    async def execute(
        self, command: DeliverOutboundRecordCommand
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        self.delivered_commands.append(command)
        dest_id = f"sink_{command.record_id}"
        return_leg_id: str | None = None
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
                        response_status_code=201,
                        response_body={"status": "OK", "external_id": dest_id},
                        duration_ms=11,
                        external_record_id=dest_id,
                    )
                    await uow.outbound_records.save(staged)
                    if command.causation_depth < self._max_causation_depth:
                        env_vo = ResponseEventEnvelope(
                            outbound_record_id=staged.id,
                            source_record_id=command.record_id or staged.id,
                            destination_id=dest_id,
                            connection_id=command.connection_id,
                            app_id=staged.app_id,
                            stream_name=command.stream_name,
                            operation=command.operation,
                            status_code=201,
                            originating_trace_id=command.original_trace_id or staged.trace_id,
                            causation_depth=command.causation_depth + 1,
                            correlation_id=command.correlation_id,
                            response_body={"status": "OK", "external_id": dest_id},
                        )
                        env_payload = env_vo.to_payload()
                        env_bytes = json.dumps(env_payload).encode("utf-8")
                        ret_records = InboundRecord.create_range_batch(
                            tenant_id=command.tenant_id,
                            connection_id=command.connection_id,
                            app_id=staged.app_id,
                            stream_name=f"{command.stream_name}__return_leg",
                            items=(
                                InboundBatchItemSpec(
                                    payload_bytes=env_bytes,
                                    is_inlined=True,
                                    request_body=env_payload,
                                    external_event_id=f"retleg:{staged.id}",
                                ),
                            ),
                            causation_depth=command.causation_depth + 1,
                            parent_trace_id=staged.trace_id,
                            original_trace_id=command.original_trace_id or staged.trace_id,
                            correlation_id=command.correlation_id,
                            ingestion_mode=IngestionMode.RETURN_LEG_CALLBACK,
                        )
                        await uow.inbound_records.save_batch(ret_records)
                        return_leg_id = ret_records[0].id
                    await uow.commit()
        return Result.ok(
            DeliverOutboundRecordResponse(
                outbound_record_id=command.idempotency_key or "out_1",
                status=OutboundDispatchStatus.DELIVERED,
                trace_id=command.trace_id or "tr_1",
                idempotency_key=command.idempotency_key or "idem_1",
                record_id=command.record_id or "rec_1",
                destination_id=dest_id,
                response_status_code=201,
                duration_ms=11,
                return_leg_inbound_record_id=return_leg_id,
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
async def test_end_to_end_pipeline_across_all_5_layers_across_lanes(
    seeded_ip_tenant: str,
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify both Realtime (N=1) and Bulk (N=4) flow L1 -> L2 -> L3 -> L4 -> L5 via Outbox Drain."""
    cp_uow = create_ip_control_plane_uow(global_session)
    tenant_resolver = SqlAlchemyIpTenantResolver(db_router=transactional_router)
    dp_uow_provider = create_ip_tenant_uow_provider(
        resolver=tenant_resolver,
        db_router=transactional_router,
    )

    connection = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="acme_source",
        name="Acme Source Endpoint",
        auth_type=AuthType.API_KEY,
        public_config={"base_url": "https://api.acme.example.com"},
        encrypted_credentials=b"enc_secret",
        endpoint_for_fingerprint="https://api.acme.example.com",
    )
    connection.activate()
    save_conn_res = await cp_uow.connections.save(connection)
    assert save_conn_res.is_ok

    entity_registry = CanonicalEntityRegistry()
    entity_registry.register(
        CanonicalEntityDefinition(
            canonical_type="canonical.record_alpha.v1",
            schema_version=1,
        )
    )
    transformer_registry = TransformerRegistry()
    transformer_registry.register(_PipelineRecordTransformer())
    canonical_writer = _PipelineCanonicalWriter()
    writer_registry: CanonicalWriterRegistry[CanonicalWriterPort] = CanonicalWriterRegistry()
    writer_registry.register(canonical_writer)

    bind_uc = BindStreamTransformationUseCase(
        control_plane_uow=cp_uow,
        transformer_registry=transformer_registry,
    )
    bind_res = await bind_uc.execute(
        BindStreamTransformationCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=connection.id,
            stream="records_alpha",
            transformation_id="acme_record_to_canonical_alpha",
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
    range_uc = ProcessInboundRangeUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_uc,
    )
    backfill_uc = BackfillStreamNormalizationUseCase(
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_uc,
    )
    stitch_dispatcher = _PipelineStitchDispatcher(dp_uow_provider, connection.id)
    delivery_executor = _PipelineOutboundDeliveryExecutor(dp_uow_provider)

    orch_dispatcher = EventEnvelopeDispatcher()
    deliv_dispatcher = EventEnvelopeDispatcher()

    def _resolve_stream_def(
        _tenant_id: str,
        _connection_id: str,
        stream_name: str,
    ) -> StreamDefinition:
        return StreamDefinition(
            stream=stream_name,
            primary_key=(("record_id",),),
            cursor_field=("observed_at",),
            cursor_kind=CursorKind.STRING,
            sync_mode=SyncMode.INCREMENTAL,
        )

    orch_registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        normalize_use_case=_PipelineNormalizeExecutor(normalize_uc),
        backfill_use_case=backfill_uc,
        process_inbound_range_use_case=_PipelineRangeExecutor(range_uc),
        stitch_dispatcher=stitch_dispatcher,
        stream_definition_resolver=_resolve_stream_def,
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

    shard_res = await dp_uow_provider.resolve_shard_info(seeded_ip_tenant)
    shard_id, shard_dsn = shard_res.unwrap()

    rt_payload: JsonDict = {
        "record_id": "REC-RT-01",
        "amount": 42.5,
        "observed_at": "2026-10-27T10:00:00Z",
    }
    rt_record = InboundRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=connection.id,
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=json.dumps(rt_payload).encode("utf-8"),
        is_inlined=True,
        request_body=rt_payload,
        trace_id="ip_trc_rt_001",
        correlation_id="REC-RT-01",
        ingestion_mode=IngestionMode.PUSH_FULL,
    )
    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save(rt_record)
        await uow.commit()

    for _ in range(6):
        drained = await drain_relay.drain_all_shards_once()
        if drained == 0:
            break

    assert "REC-RT-01" in canonical_writer.rows
    assert canonical_writer.rows["REC-RT-01"]["amount"] == 42.5
    assert any(
        c.record_id == "REC-RT-01"
        and c.payload.get("amount") == 42.5
        and c.payload.get("status") == "ACTIVE"
        for c in delivery_executor.delivered_commands
    )
    # 2-Queue Boundary invariant: zero internal replica/canonical hops on orchestrator queues;
    # only initial L1 ingress + L5->L1 return-leg callback (`causation_depth=1`) hit ingress queue!
    orch_rt_types = [e.event_type for e in orch_rt_bridge.published_envelopes]
    assert orch_rt_types == [
        IpEventType.INBOUND_RECORD_CREATED.value,
        IpEventType.INBOUND_RECORD_CREATED.value,
    ]
    assert orch_rt_bridge.published_envelopes[1].payload.get("causation_depth") == 1
    assert [e.event_type for e in deliv_rt_bridge.published_envelopes] == [
        IpEventType.OUTBOUND_RECORD_CREATED.value
    ]

    bulk_specs = tuple(
        InboundBatchItemSpec(
            payload_bytes=json.dumps(
                {
                    "record_id": f"REC-BLK-0{idx}",
                    "amount": float(idx * 100),
                    "observed_at": "2026-10-27T11:00:00Z",
                }
            ).encode("utf-8"),
            is_inlined=True,
            request_body={
                "record_id": f"REC-BLK-0{idx}",
                "amount": float(idx * 100),
                "observed_at": "2026-10-27T11:00:00Z",
            },
        )
        for idx in range(1, 5)
    )
    bulk_range_records = InboundRecord.create_range_batch(
        tenant_id=seeded_ip_tenant,
        connection_id=connection.id,
        app_id="acme_source",
        stream_name="records_alpha",
        items=bulk_specs,
        trace_id="ip_trc_bulk_001",
        correlation_id="BATCH-BLK-01",
        ingestion_mode=IngestionMode.PULL_INCREMENTAL,
    )
    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save_batch(bulk_range_records)
        await uow.commit()

    for _ in range(6):
        drained = await drain_relay.drain_all_shards_once()
        if drained == 0:
            break

    for idx in range(1, 5):
        rec_key = f"REC-BLK-0{idx}"
        assert rec_key in canonical_writer.rows
        assert canonical_writer.rows[rec_key]["amount"] == float(idx * 100)
        assert any(
            c.record_id == rec_key
            and c.payload.get("amount") == float(idx * 100)
            and c.payload.get("status") == "ACTIVE"
            for c in delivery_executor.delivered_commands
        )

    inb_bulk_envelopes = [
        env
        for env in orch_bulk_bridge.published_envelopes
        if env.event_type == IpEventType.INBOUND_RECORD_CREATED.value
    ]
    assert len(inb_bulk_envelopes) == 1
    inb_bulk_env = inb_bulk_envelopes[0]
    assert inb_bulk_env.lane is EventProcessingLane.BULK
    assert inb_bulk_env.payload.get("count") == 4
    assert inb_bulk_env.payload.get("range_start") == bulk_range_records[0].id
    assert inb_bulk_env.payload.get("range_end") == bulk_range_records[-1].id
    assert all(
        env.event_type == IpEventType.INBOUND_RECORD_CREATED.value
        for env in orch_bulk_bridge.published_envelopes
    )

    session_yielded = False
    async for verify_session in transactional_router.get_tenant_session(
        seeded_ip_tenant, shard_id, shard_dsn
    ):
        session_yielded = True
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
        assert IpTraceEventType.INGEST_RECEIVED.value in event_types_seen
        assert IpTraceEventType.REPLICA_CREATED.value in event_types_seen
        assert IpTraceEventType.NORMALIZED.value in event_types_seen
        assert IpTraceEventType.DISPATCH_DELIVERED.value in event_types_seen

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

    assert session_yielded, "Expected get_tenant_session to yield a session for verification"
