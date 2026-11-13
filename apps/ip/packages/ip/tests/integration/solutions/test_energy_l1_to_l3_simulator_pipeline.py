"""End-to-End PostgreSQL Integration Tests for the Energy Sector L1 -> L3 Pipeline.

Exercises the complete Layer 1 to Layer 3 pipeline for Energy Smart Grid MDM:
1. Universal Schema Simulator (`universal_simulator`, `NO_AUTH`) connection provisioning.
2. Connection-scoped entity creation for Energy streams:
   - `service_points` (sample premise/meter blueprint)
   - `meter_readings` (sample interval meter reading blueprint)
3. Schema inference & catalog discovery (`POST /discover`) -> entity subscription in `ConnectionEntity`.
4. Pure L3 canonical transformation bindings:
   - `service_points` -> `energy.ami_service_point` (v1) in ACTIVE mode
   - `meter_readings` -> `energy.ami_meter_reading` (v2) in ACTIVE mode
5. Pull Sync Pipeline (`RunSyncUseCase`):
   - Generates deterministic records from `ip.simulator_entities`.
   - Persists raw payloads to Layer 1 (`inbound_records`) with mode `PULL_INITIAL`.
   - Stages transactional outbox events (`ip.inbound_record.created`).
   - Drains outbox via `MultiShardOutboxDrainRelay` -> `EventEnvelopeDispatcher` -> `IpOrchestratorRouteRegistry`.
   - Executes fused Layer 2 -> Layer 3 range processing (`ProcessInboundRangeUseCase`):
     - Dynamically resolves stream primary key/cursor from subscribed `ConnectionEntity`.
     - Replicates to `replica_records` (L2).
     - Normalizes to canonical Energy domain tables: `mdm_service_points` and `mdm_meter_readings` (L3).
     - Persists `normalized_records` and `entity_maps`.
   - Verifies content-hash deduplication (`MergeOutcome.NOOP`) on subsequent sync.
6. Push Webhook & Late-Arriving Reference Resolution:
   - Ingests an out-of-order meter reading referencing a not-yet-created service point.
   - Verifies entry recorded in `pending_references`.
   - Ingests the corresponding service point -> verifies back-patching resolves `mdm_meter_readings.service_point_id` to the canonical service point ID.
7. Enterprise Observability:
   - Verifies structured trace events in `ip_trace_events` across the full lifecycle.

All tests run against real PostgreSQL inside nested SAVEPOINT transactions (`TransactionalTestRouter`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence

import pytest
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
    IpNormalizeReplicaExecutorPort,
    IpOrchestratorRouteRegistry,
    IpProcessInboundRangeExecutorPort,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    InboundRecordModel,
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
    NormalizedRecordModel,
    PendingReferenceModel,
    ReplicaRecordModel,
)
from ip.engine.adapters.outbound.database.tenant_resolver import (
    SqlAlchemyIpTenantResolver,
)
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncUseCase,
)
from ip.engine.application.use_cases.normalization.backfill_stream_normalization_use_case import (
    BackfillStreamNormalizationCommand,
    BackfillStreamNormalizationResultDTO,
    BackfillStreamNormalizationUseCase,
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
from ip.engine.bootstrap.container import Container, create_ip_control_plane_uow
from ip.engine.bootstrap.publisher_factory import build_ip_dp_outbox_router
from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.enums import IpOutboxSource
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.replication.connection_entity import (
    ConnectionEntity,
    EntitySyncFrom,
    EntitySyncSchedule,
)
from ip.engine.domain.replication.enums import (
    IngestionMode,
    SyncMode,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.trace.enums import IpTraceEventType
from ip.module import IpApiModule
from ip.solutions.bootstrap import configure_solution_container
from ip.solutions.domains.energy.canonical import EnergyEntityType
from ip.solutions.domains.energy.models import (
    MdmMeterReadingRecord,
    MdmServicePointRecord,
)
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository
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
from seedwork.events import EventEnvelope
from sqlalchemy import select

pytestmark = pytest.mark.integration

_TEST_KEY_BYTES = b"0123456789abcdef0123456789abcdef"


class _InMemoryQueueBridgePublisher(OutboxPublisherPort):
    """Directly dispatches published Outbox events into an EventEnvelopeDispatcher."""

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


class _PipelineRangeExecutor(IpProcessInboundRangeExecutorPort):
    """Adapts ProcessInboundRangeUseCase for IpOrchestratorRouteRegistry."""

    def __init__(self, use_case: ProcessInboundRangeUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self, command: ProcessInboundRangeCommand
    ) -> Result[ProcessInboundRangeResultDTO, IpError]:
        return await self._use_case.execute(command)


class _PipelineNormalizeExecutor(IpNormalizeReplicaExecutorPort):
    """Adapts NormalizeReplicaRecordUseCase for IpOrchestratorRouteRegistry."""

    def __init__(self, use_case: NormalizeReplicaRecordUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self, command: NormalizeReplicaRecordCommand
    ) -> Result[NormalizeReplicaRecordResultDTO, IpError]:
        return await self._use_case.execute(command)


class _PipelineBackfillExecutor(IpBackfillStreamNormalizationExecutorPort):
    """Adapts BackfillStreamNormalizationUseCase for IpOrchestratorRouteRegistry."""

    def __init__(self, use_case: BackfillStreamNormalizationUseCase) -> None:
        self._use_case = use_case

    async def execute(
        self, command: BackfillStreamNormalizationCommand
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        return await self._use_case.execute(command)


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


def _build_outbox_drain_pipeline(
    *,
    container: Container,
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
) -> tuple[MultiShardOutboxDrainRelay, _InMemoryQueueBridgePublisher, ProcessInboundRangeUseCase]:
    cp_uow = create_ip_control_plane_uow(global_session)
    dp_uow_provider = container.dp_uow_provider()

    normalize_uc = container.normalize_replica_record_use_case(control_plane_uow=cp_uow)
    range_uc = container.process_inbound_range_use_case(
        control_plane_uow=cp_uow,
        normalize_use_case=normalize_uc,
    )
    backfill_uc = BackfillStreamNormalizationUseCase(
        data_plane_uow_provider=dp_uow_provider,
        normalize_use_case=normalize_uc,
    )

    orch_dispatcher = EventEnvelopeDispatcher()
    orch_registry = IpOrchestratorRouteRegistry(
        dp_uow_provider=dp_uow_provider,
        normalize_use_case=_PipelineNormalizeExecutor(normalize_uc),
        backfill_use_case=_PipelineBackfillExecutor(backfill_uc),
        process_inbound_range_use_case=_PipelineRangeExecutor(range_uc),
        stream_definition_resolver=None,  # Resolves dynamically from subscribed ConnectionEntity!
        max_chunk_concurrency=4,
    )
    orch_registry.register_routes(orch_dispatcher)

    orch_bridge = _InMemoryQueueBridgePublisher(orch_dispatcher)
    noop_bridge = _InMemoryQueueBridgePublisher(EventEnvelopeDispatcher())

    dp_router = build_ip_dp_outbox_router(
        orchestrator_realtime_publisher=orch_bridge,
        orchestrator_bulk_publisher=orch_bridge,
        delivery_realtime_publisher=noop_bridge,
        delivery_bulk_publisher=noop_bridge,
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
    return drain_relay, orch_bridge, range_uc


async def _drain_outbox_fully(
    drain_relay: MultiShardOutboxDrainRelay, max_iterations: int = 6
) -> None:
    for _ in range(max_iterations):
        drained = await drain_relay.drain_all_shards_once()
        if drained == 0:
            break


def _assert_sp_replica_rows(rep_sp_rows: Sequence[ReplicaRecordModel]) -> None:
    assert len(rep_sp_rows) == 5
    for r in rep_sp_rows:
        assert r.deleted_at is None
        assert r.version == 1
        assert r.data_hash != ""


def _assert_canonical_sp_rows(canonical_sp_rows: Sequence[MdmServicePointRecord]) -> None:
    assert len(canonical_sp_rows) == 5
    for sp in canonical_sp_rows:
        assert sp.transformation_id == "energy.ami_service_point"
        assert sp.transformation_version == 1
        assert sp.status in {"ACTIVE", "CREATED", "APPROVED", "IN_TRANSIT", "COMPLETED", "SETTLED"}


def _assert_canonical_mr_rows(canonical_mr_rows: Sequence[MdmMeterReadingRecord]) -> None:
    assert len(canonical_mr_rows) == 5
    for mr in canonical_mr_rows:
        assert mr.transformation_id == "energy.ami_meter_reading"
        assert mr.transformation_version == 2
        assert mr.voltage_avg is not None
        assert mr.kwh_delivered >= 0.0


@pytest.mark.asyncio
async def test_energy_l1_to_l3_simulator_pull_sync_pipeline(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Verifies end-to-end Energy sector Pull Sync pipeline (L1 Ingress -> Outbox -> L2 Replica -> L3 Canonical)."""
    admin_ctx = IdentityContext(
        subject="usr_energy_admin",
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
    cp_uow = create_ip_control_plane_uow(global_session)

    drain_relay, _orch_bridge, _ = _build_outbox_drain_pipeline(
        container=container,
        global_session=global_session,
        transactional_router=transactional_router,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Pre-flight Check & Provision Universal Simulator Connection
        check_res = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/check",
            json={
                "app_id": "universal_simulator",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 1001, "records_per_pull": 5},
                "raw_credentials": {},
            },
        )
        assert check_res.status_code == 200
        assert check_res.json()["success"] is True

        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "ERCOT Smart Grid Simulator",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 1001, "records_per_pull": 5},
                "raw_credentials": {},
                "endpoint_for_fingerprint": "ERCOT Smart Grid Simulator",
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]

        # 2. Create Simulator Entities for Energy sector: `service_points` and `meter_readings`
        sp_ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "service_points",
                "sample_blueprint": {
                    "service_point_id": "SP-1001",
                    "meter_serial": "MTR-5001",
                    "customer_id": "CUST-9001",
                    "service_address": "1001 Grid Power Way, Austin TX",
                    "grid_region": "ERCOT_NORTH",
                    "status": "ACTIVE",
                    "updated_at": "2026-11-12T00:00:00Z",
                },
                "records_per_pull": 5,
            },
        )
        assert sp_ent_resp.status_code == 201
        sp_ent_body = sp_ent_resp.json()
        assert sp_ent_body["primary_key_field"] == "service_point_id"
        assert sp_ent_body["cursor_field"] == "updated_at"

        mr_ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "meter_readings",
                "sample_blueprint": {
                    "reading_id": "MR-80001",
                    "meter_serial": "MTR-5001",
                    "service_point_id": "SP-1001",
                    "timestamp": "2026-11-12T00:15:00Z",
                    "interval_minutes": 15,
                    "kwh_delivered": 42.5,
                    "kwh_received": 1.2,
                    "voltage_avg": 240.1,
                    "quality": "VALIDATED",
                },
                "records_per_pull": 5,
            },
        )
        assert mr_ent_resp.status_code == 201
        mr_ent_body = mr_ent_resp.json()
        assert mr_ent_body["primary_key_field"] == "reading_id"
        assert mr_ent_body["cursor_field"] == "timestamp"

        # 3. Discover Catalog -> Verifies dynamic synthesis schema
        disc_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/discover"
        )
        assert disc_resp.status_code == 200
        discovered_streams = {s["name"]: s for s in disc_resp.json()["streams"]}
        assert "service_points" in discovered_streams
        assert "meter_readings" in discovered_streams

        # 4. Subscribe to both entities in `ConnectionEntity` table
        sp_entity = ConnectionEntity(
            id=f"ip_ce_sp_{connection_id[-8:]}",
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="service_points",
            sync_mode=SyncMode.INCREMENTAL,
            schedule=EntitySyncSchedule.HOURLY,
            sync_from=EntitySyncFrom.ALL,
            is_enabled=True,
            primary_key=("service_point_id",),
            cursor_field="updated_at",
            fields=(
                StreamField("service_point_id", "STRING", nullable=False),
                StreamField("meter_serial", "STRING", nullable=True),
                StreamField("customer_id", "STRING", nullable=True),
                StreamField("service_address", "STRING", nullable=True),
                StreamField("grid_region", "STRING", nullable=True),
                StreamField("status", "STRING", nullable=False),
                StreamField("updated_at", "DATETIME", nullable=False),
            ),
        )
        mr_entity = ConnectionEntity(
            id=f"ip_ce_mr_{connection_id[-8:]}",
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="meter_readings",
            sync_mode=SyncMode.INCREMENTAL,
            schedule=EntitySyncSchedule.HOURLY,
            sync_from=EntitySyncFrom.ALL,
            is_enabled=True,
            primary_key=("reading_id",),
            cursor_field="timestamp",
            fields=(
                StreamField("reading_id", "STRING", nullable=False),
                StreamField("meter_serial", "STRING", nullable=False),
                StreamField("service_point_id", "STRING", nullable=True),
                StreamField("timestamp", "DATETIME", nullable=False),
                StreamField("interval_minutes", "INTEGER", nullable=False),
                StreamField("kwh_delivered", "NUMBER", nullable=False),
                StreamField("kwh_received", "NUMBER", nullable=False),
                StreamField("voltage_avg", "NUMBER", nullable=True),
                StreamField("quality", "STRING", nullable=False),
            ),
        )
        await cp_uow.entities.save(sp_entity)
        await cp_uow.entities.save(mr_entity)
        await cp_uow.commit()

        # 5. Bind Stream Transformations:
        # `service_points` -> `energy.ami_service_point` (v1)
        # `meter_readings` -> `energy.ami_meter_reading` (v2)
        bind_sp_resp = await client.put(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/transformations/connections/{connection_id}/streams/service_points",
            json={
                "transformation_id": "energy.ami_service_point",
                "transformation_version": 1,
                "mode": "ACTIVE",
            },
        )
        assert bind_sp_resp.status_code == 200

        bind_mr_resp = await client.put(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/transformations/connections/{connection_id}/streams/meter_readings",
            json={
                "transformation_id": "energy.ami_meter_reading",
                "transformation_version": 2,
                "mode": "ACTIVE",
            },
        )
        assert bind_mr_resp.status_code == 200

    # 6. Execute Pull Sync for `service_points` (5 records)
    token_mgr = TokenManagerService(control_plane_uow=cp_uow, cipher=container.cipher())
    run_sync_uc = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=container.dp_uow_provider(),
        tiered_storage=container.tiered_storage(),
        cipher=container.cipher(),
        connectors=container.connector_mapping(),
        token_manager=token_mgr,
    )
    sync_sp_dto = await run_sync_uc.execute(
        RunSyncCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="service_points",
        )
    )
    assert sync_sp_dto.status == "SUCCEEDED"
    assert sync_sp_dto.records_synced == 5
    assert sync_sp_dto.pages_synced >= 1

    # Verify L1 `inbound_records` has 1 batch record with `PULL_INITIAL`
    inb_sp_rows = (
        (
            await tenant_session.execute(
                select(InboundRecordModel).where(
                    InboundRecordModel.tenant_id == seeded_ip_tenant,
                    InboundRecordModel.connection_id == connection_id,
                    InboundRecordModel.stream_name == "service_points",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(inb_sp_rows) == 1
    assert inb_sp_rows[0].ingestion_mode == IngestionMode.PULL_INITIAL.value
    assert inb_sp_rows[0].request_size_bytes > 0

    # Drain Outbox -> Runs fused L2 Replica extraction + L3 Normalization
    await _drain_outbox_fully(drain_relay)
    tenant_session.expire_all()

    # Verify L2 `replica_records` has 5 rows
    rep_sp_rows = (
        (
            await tenant_session.execute(
                select(ReplicaRecordModel).where(
                    ReplicaRecordModel.tenant_id == seeded_ip_tenant,
                    ReplicaRecordModel.connection_id == connection_id,
                    ReplicaRecordModel.stream == "service_points",
                )
            )
        )
        .scalars()
        .all()
    )
    _assert_sp_replica_rows(rep_sp_rows)

    # Verify L3 `mdm_service_points` canonical table has 5 rows
    canonical_sp_rows = (
        (
            await tenant_session.execute(
                select(MdmServicePointRecord).where(
                    MdmServicePointRecord.tenant_id == seeded_ip_tenant,
                    MdmServicePointRecord.source_connection_id == connection_id,
                )
            )
        )
        .scalars()
        .all()
    )
    _assert_canonical_sp_rows(canonical_sp_rows)

    # Verify L3 `normalized_records` and `entity_maps`
    norm_sp_records = (
        (
            await tenant_session.execute(
                select(NormalizedRecordModel).where(
                    NormalizedRecordModel.tenant_id == seeded_ip_tenant,
                    NormalizedRecordModel.canonical_type
                    == EnergyEntityType.MDM_SERVICE_POINT.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(norm_sp_records) == 5

    # 7. Execute Pull Sync for `meter_readings` (5 records)
    sync_mr_dto = await run_sync_uc.execute(
        RunSyncCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="meter_readings",
        )
    )
    assert sync_mr_dto.status == "SUCCEEDED"
    assert sync_mr_dto.records_synced == 5

    # Drain Outbox -> Runs fused L2 Replica extraction + L3 Normalization
    await _drain_outbox_fully(drain_relay)
    tenant_session.expire_all()

    # Verify L2 `replica_records` has 5 rows for `meter_readings`
    rep_mr_rows = (
        (
            await tenant_session.execute(
                select(ReplicaRecordModel).where(
                    ReplicaRecordModel.tenant_id == seeded_ip_tenant,
                    ReplicaRecordModel.connection_id == connection_id,
                    ReplicaRecordModel.stream == "meter_readings",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rep_mr_rows) == 5

    # Verify L3 `mdm_meter_readings` canonical table has 5 rows with v2 features (voltage_avg)
    canonical_mr_rows = (
        (
            await tenant_session.execute(
                select(MdmMeterReadingRecord).where(
                    MdmMeterReadingRecord.tenant_id == seeded_ip_tenant,
                    MdmMeterReadingRecord.source_connection_id == connection_id,
                )
            )
        )
        .scalars()
        .all()
    )
    _assert_canonical_mr_rows(canonical_mr_rows)

    # 8. Re-run Pull Sync to verify L2 Content-Hash Deduplication (`MergeOutcome.NOOP`)
    # Re-running with same seed produces identical payload -> NOOP merge outcome
    sync_sp_repeat = await run_sync_uc.execute(
        RunSyncCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="service_points",
        )
    )
    assert sync_sp_repeat.status == "SUCCEEDED"

    await _drain_outbox_fully(drain_relay)
    tenant_session.expire_all()

    # Replica versions must remain 1 (no spurious updates or duplicate inserts)
    rep_sp_after_repeat = (
        (
            await tenant_session.execute(
                select(ReplicaRecordModel).where(
                    ReplicaRecordModel.tenant_id == seeded_ip_tenant,
                    ReplicaRecordModel.connection_id == connection_id,
                    ReplicaRecordModel.stream == "service_points",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rep_sp_after_repeat) == 5
    for r in rep_sp_after_repeat:
        assert r.version == 1

    # Canonical rows remain 5
    final_sp_rows = (
        (
            await tenant_session.execute(
                select(MdmServicePointRecord).where(
                    MdmServicePointRecord.tenant_id == seeded_ip_tenant,
                    MdmServicePointRecord.source_connection_id == connection_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(final_sp_rows) == 5


@pytest.mark.asyncio
async def test_energy_l1_to_l3_push_webhook_out_of_order_reference_resolution(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Verifies Push Webhook ingress and out-of-order reference back-patching in the Energy domain."""
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
    cp_uow = create_ip_control_plane_uow(global_session)

    drain_relay, _orch_bridge, _ = _build_outbox_drain_pipeline(
        container=container,
        global_session=global_session,
        transactional_router=transactional_router,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Create Connection
        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "Itron Head-End Webhook Connection",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 9002},
                "raw_credentials": {},
                "endpoint_for_fingerprint": "Itron Head-End Webhook Connection",
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]

        # 2. Subscribe to `meter_readings` and `service_points`
        mr_entity = ConnectionEntity(
            id=f"ip_ce_mr_push_{connection_id[-6:]}",
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="meter_readings",
            sync_mode=SyncMode.INCREMENTAL,
            schedule=EntitySyncSchedule.MANUAL,
            sync_from=EntitySyncFrom.ALL,
            is_enabled=True,
            primary_key=("reading_id",),
            cursor_field="timestamp",
            fields=(
                StreamField("reading_id", "STRING", nullable=False),
                StreamField("meter_serial", "STRING", nullable=False),
                StreamField("service_point_id", "STRING", nullable=True),
                StreamField("timestamp", "DATETIME", nullable=False),
                StreamField("interval_minutes", "INTEGER", nullable=False),
                StreamField("kwh_delivered", "NUMBER", nullable=False),
                StreamField("kwh_received", "NUMBER", nullable=False),
                StreamField("voltage_avg", "NUMBER", nullable=True),
                StreamField("quality", "STRING", nullable=False),
            ),
        )
        sp_entity = ConnectionEntity(
            id=f"ip_ce_sp_push_{connection_id[-6:]}",
            tenant_id=seeded_ip_tenant,
            connection_id=connection_id,
            stream_name="service_points",
            sync_mode=SyncMode.INCREMENTAL,
            schedule=EntitySyncSchedule.MANUAL,
            sync_from=EntitySyncFrom.ALL,
            is_enabled=True,
            primary_key=("service_point_id",),
            cursor_field="updated_at",
            fields=(
                StreamField("service_point_id", "STRING", nullable=False),
                StreamField("meter_serial", "STRING", nullable=True),
                StreamField("customer_id", "STRING", nullable=True),
                StreamField("service_address", "STRING", nullable=True),
                StreamField("grid_region", "STRING", nullable=True),
                StreamField("status", "STRING", nullable=False),
                StreamField("updated_at", "DATETIME", nullable=False),
            ),
        )
        await cp_uow.entities.save(mr_entity)
        await cp_uow.entities.save(sp_entity)
        await cp_uow.commit()

        # 3. Bind transformations
        await client.put(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/transformations/connections/{connection_id}/streams/meter_readings",
            json={
                "transformation_id": "energy.ami_meter_reading",
                "transformation_version": 2,
                "mode": "ACTIVE",
            },
        )
        await client.put(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/transformations/connections/{connection_id}/streams/service_points",
            json={
                "transformation_id": "energy.ami_service_point",
                "transformation_version": 1,
                "mode": "ACTIVE",
            },
        )

    # 4. Ingest an out-of-order meter reading (references premise 'SP-LATE-888' which does NOT exist yet)
    dp_uow_provider = container.dp_uow_provider()
    shard_res = await dp_uow_provider.resolve_shard_info(seeded_ip_tenant)
    shard_id, shard_dsn = shard_res.unwrap()

    reading_payload: JsonDict = {
        "reading_id": "MR-LATE-888-01",
        "meter_serial": "MTR-LATE-888",
        "service_point_id": "SP-LATE-888",
        "timestamp": "2026-11-12T01:15:00Z",
        "interval_minutes": 15,
        "kwh_delivered": 18.75,
        "kwh_received": 0.5,
        "voltage_avg": 240.5,
        "quality": "VALIDATED",
    }
    reading_inb = InboundRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=connection_id,
        app_id="universal_simulator",
        stream_name="meter_readings",
        payload_bytes=json.dumps(reading_payload).encode("utf-8"),
        is_inlined=True,
        request_body=reading_payload,
        trace_id="ip_trc_late_mr_001",
        correlation_id="MR-LATE-888-01",
        ingestion_mode=IngestionMode.PUSH_FULL,
    )
    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save(reading_inb)
        await uow.commit()

    # Drain outbox to process meter reading
    await _drain_outbox_fully(drain_relay)
    tenant_session.expire_all()

    # Verify: reading is persisted in `mdm_meter_readings` with raw external ID
    energy_repo = SqlAlchemyEnergyDomainRepository(tenant_session)
    readings = await energy_repo.list_readings_by_meter(seeded_ip_tenant, "MTR-LATE-888")
    assert len(readings) == 1
    assert readings[0].meter_serial_number == "MTR-LATE-888"
    assert readings[0].service_point_id == "SP-LATE-888"
    assert readings[0].voltage_avg == 240.5

    # Verify: an entry exists in `pending_references` with status PENDING
    pending_refs = (
        (
            await tenant_session.execute(
                select(PendingReferenceModel).where(
                    PendingReferenceModel.tenant_id == seeded_ip_tenant,
                    PendingReferenceModel.source_connection_id == connection_id,
                    PendingReferenceModel.target_source_id == "SP-LATE-888",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(pending_refs) == 1
    assert pending_refs[0].status == "PENDING"
    assert pending_refs[0].referencing_field == "service_point_id"

    # 5. Ingest the late-arriving Service Point: `SP-LATE-888`
    sp_payload: JsonDict = {
        "service_point_id": "SP-LATE-888",
        "meter_serial": "MTR-LATE-888",
        "customer_id": "CUST-LATE-888",
        "service_address": "888 Late Substation Road, Dallas TX",
        "grid_region": "ERCOT_NORTH",
        "status": "ACTIVE",
        "updated_at": "2026-11-12T01:30:00Z",
    }
    sp_inb = InboundRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=connection_id,
        app_id="universal_simulator",
        stream_name="service_points",
        payload_bytes=json.dumps(sp_payload).encode("utf-8"),
        is_inlined=True,
        request_body=sp_payload,
        trace_id="ip_trc_late_sp_001",
        correlation_id="SP-LATE-888",
        ingestion_mode=IngestionMode.PUSH_FULL,
    )
    async with dp_uow_provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        await uow.inbound_records.save(sp_inb)
        await uow.commit()

    # Drain outbox to process service point AND trigger late reference resolution
    await _drain_outbox_fully(drain_relay)
    tenant_session.expire_all()

    # Verify: service point is saved in `mdm_service_points`
    saved_sp = await energy_repo.get_service_point_by_external_id(seeded_ip_tenant, "SP-LATE-888")
    assert saved_sp is not None
    assert saved_sp.service_point_external_id == "SP-LATE-888"
    assert saved_sp.meter_serial_number == "MTR-LATE-888"

    # Verify: `mdm_meter_readings.service_point_id` was automatically back-patched to the canonical service point ID!
    updated_readings = await energy_repo.list_readings_by_meter(seeded_ip_tenant, "MTR-LATE-888")
    assert len(updated_readings) == 1
    assert updated_readings[0].service_point_id == saved_sp.id
    assert updated_readings[0].service_point_id != "SP-LATE-888"

    # Verify: `pending_references` entry status transitioned to RESOLVED
    tenant_session.expire_all()
    resolved_refs = (
        (
            await tenant_session.execute(
                select(PendingReferenceModel).where(
                    PendingReferenceModel.tenant_id == seeded_ip_tenant,
                    PendingReferenceModel.source_connection_id == connection_id,
                    PendingReferenceModel.target_source_id == "SP-LATE-888",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(resolved_refs) == 1
    assert resolved_refs[0].status == "RESOLVED"
    assert resolved_refs[0].resolved_at is not None

    # 6. Verify Enterprise Observability Lineage (`ip_trace_events`)
    trace_events = (
        (
            await tenant_session.execute(
                select(IpTraceEventModel)
                .where(IpTraceEventModel.tenant_id == seeded_ip_tenant)
                .order_by(IpTraceEventModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(trace_events) > 0
    event_types = {e.event_type for e in trace_events}
    assert IpTraceEventType.INGEST_RECEIVED.value in event_types
    assert IpTraceEventType.REPLICA_CREATED.value in event_types
    assert IpTraceEventType.NORMALIZED.value in event_types
    assert IpTraceEventType.REFERENCE_PENDING.value in event_types
    assert IpTraceEventType.REFERENCE_RESOLVED.value in event_types
