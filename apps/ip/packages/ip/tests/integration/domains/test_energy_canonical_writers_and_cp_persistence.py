"""Narrow PostgreSQL Integration Tests for Energy Canonical Writers, Stitch Persistence, and Advisory Token Refresh Locks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from dependency_injector import providers
from ip.application.domains.energy.canonical import EnergyEntityType
from ip.application.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    SqlAlchemyTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.application.use_cases.normalization.bind_stream_transformation_use_case import (
    BindStreamTransformationCommand,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
)
from ip.engine.application.use_cases.stitch.stitch_control_plane_use_cases import (
    ListStitchesQuery,
    ListStitchesUseCase,
    RegisterStitchCommand,
    RegisterStitchUseCase,
)
from ip.engine.container import Container
from ip.engine.domain.enums import (
    AuthType,
    IpEventType,
    NormalizationOutcome,
    TransformationMode,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.stitch import StitchStepType
from orchestration.ports.inbound.step_handler_port import StepContext
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_energy_canonical_writers_and_step_handlers_in_container_on_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Verifies Container wires Energy canonical writers (`mdm_meter_readings`, `mdm_service_points`)
    and all 3 Stitch step handlers against PostgreSQL, including out-of-order reference back-patching.
    """
    resolver = IpTenantResolver(transactional_router)
    container = Container()
    container.config.allow_private_ips.from_value(True)
    container.db_router.override(providers.Object(transactional_router))
    container.tenant_resolver.override(providers.Object(resolver))

    cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    dp_uow = SqlAlchemyIpDataPlaneUnitOfWork(tenant_session)
    now = datetime.now(UTC)
    conn_id = "ip_conn_itron_energy_01"

    conn = Connection(
        id=conn_id,
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Itron Smart Grid MDM",
        auth_type=AuthType.BEARER_TOKEN,
        public_config={"base_url": "https://api.itron.example.com"},
        encrypted_credentials=b"enc",
        connection_fingerprint="fp_energy_001",
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    await cp_uow.connections.save(conn)
    await cp_uow.commit()

    bind_uc = container.bind_stream_transformation_use_case(control_plane_uow=cp_uow)
    res_bind_reading = await bind_uc.execute(
        BindStreamTransformationCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn_id,
            stream="meter_readings",
            transformation_id="energy.ami_meter_reading",
            transformation_version=2,
            mode=TransformationMode.ACTIVE,
        )
    )
    assert res_bind_reading.is_ok

    res_bind_sp = await bind_uc.execute(
        BindStreamTransformationCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn_id,
            stream="service_points",
            transformation_id="energy.ami_service_point",
            transformation_version=1,
            mode=TransformationMode.ACTIVE,
        )
    )
    assert res_bind_sp.is_ok

    # 1. Insert ReplicaRecord for a meter reading referencing unseen service_point_id='SP-ERCOT-700'
    reading_rep = ReplicaRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn_id,
        stream="meter_readings",
        record_key="MTR-700:2026-10-27T12:00:00Z",
        data={
            "meter_serial": "MTR-700",
            "service_point_id": "SP-ERCOT-700",
            "timestamp": "2026-10-27T12:00:00Z",
            "interval_minutes": 15,
            "kwh_delivered": 32.5,
            "kwh_received": 1.5,
            "voltage_avg": 240.8,
            "quality": "VALIDATED",
        },
        cursor_value="2026-10-27T12:00:00Z",
        source_inbound_record_id="ip_inb_energy_700",
        trace_id="ip_trc_energy_700",
        correlation_id="MTR-700",
    )
    await dp_uow.replica_records.save(reading_rep)
    await dp_uow.commit()

    norm_uc = container.normalize_replica_record_use_case(control_plane_uow=cp_uow)
    norm_reading_res = await norm_uc.execute(
        NormalizeReplicaRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn_id,
            stream="meter_readings",
            replica_record_id=reading_rep.id,
            replica_version=reading_rep.version,
            trace_id="ip_trc_energy_700",
            correlation_id="MTR-700",
        )
    )
    assert norm_reading_res.is_ok
    assert norm_reading_res.unwrap().outcome is NormalizationOutcome.NORMALIZED

    energy_repo = SqlAlchemyEnergyDomainRepository(tenant_session)
    readings = await energy_repo.list_readings_by_meter(seeded_ip_tenant, "MTR-700")
    assert len(readings) == 1
    assert readings[0].kwh_delivered == 32.5
    assert readings[0].voltage_avg == 240.8
    assert readings[0].service_point_id == "SP-ERCOT-700"
    assert readings[0].transformation_id == "energy.ami_meter_reading"
    assert readings[0].transformation_version == 2

    # 2. Now normalize the late-arriving Service Point 'SP-ERCOT-700' and verify back-patching
    sp_rep = ReplicaRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn_id,
        stream="service_points",
        record_key="SP-ERCOT-700",
        data={
            "service_point_id": "SP-ERCOT-700",
            "meter_id": "MTR-700",
            "customer_id": "CUST-700",
            "address": "700 Grid Substation Way",
            "status": "ACTIVE",
        },
        cursor_value="2026-10-27T12:01:00Z",
        source_inbound_record_id="ip_inb_sp_700",
        trace_id="ip_trc_sp_700",
        correlation_id="SP-ERCOT-700",
    )
    await dp_uow.replica_records.save(sp_rep)
    await dp_uow.commit()

    norm_sp_res = await norm_uc.execute(
        NormalizeReplicaRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn_id,
            stream="service_points",
            replica_record_id=sp_rep.id,
            replica_version=sp_rep.version,
            trace_id="ip_trc_sp_700",
            correlation_id="SP-ERCOT-700",
        )
    )
    assert norm_sp_res.is_ok
    sp_outcome = norm_sp_res.unwrap()
    assert sp_outcome.outcome is NormalizationOutcome.NORMALIZED
    assert sp_outcome.resolved_references_count == 1

    saved_sp = await energy_repo.get_service_point_by_external_id(seeded_ip_tenant, "SP-ERCOT-700")
    assert saved_sp is not None
    assert saved_sp.meter_serial_number == "MTR-700"
    assert saved_sp.transformation_id == "energy.ami_service_point"
    assert saved_sp.transformation_version == 1

    # The meter reading's service_point_id should now be back-patched to saved_sp.id!
    updated_readings = await energy_repo.list_readings_by_meter(seeded_ip_tenant, "MTR-700")
    assert len(updated_readings) == 1
    assert updated_readings[0].service_point_id == saved_sp.id

    # 3. Verify all 3 Stitch step handlers are registered in Container.step_handler_registry
    step_reg = container.step_handler_registry()
    query_handler_res = step_reg.get(StitchStepType.QUERY_REPLICA.value)
    notify_handler_res = step_reg.get(StitchStepType.EMIT_NOTIFICATION.value)
    http_handler_res = step_reg.get(StitchStepType.EXECUTE_HTTP_ACTION.value)
    assert query_handler_res.is_ok
    assert notify_handler_res.is_ok
    assert http_handler_res.is_ok

    step_ctx = StepContext(
        tenant_id=seeded_ip_tenant,
        run_id="wfr_energy_01",
        step_run_id="wfs_energy_01",
        node_key="lookup_service_point",
        idempotency_key="idem_energy_step_01",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        deadline=datetime(2026, 10, 27, 23, 0, 0, tzinfo=UTC),
        trace_id="ip_trc_energy_700",
        correlation_id="MTR-700",
    )
    q_res = await query_handler_res.unwrap().execute(
        step_ctx,
        {
            "connection_id": conn_id,
            "stream": "service_points",
            "record_key": "SP-ERCOT-700",
        },
    )
    assert q_res.is_ok
    assert q_res.unwrap()["found"] is True
    assert q_res.unwrap()["record_id"] == sp_rep.id

    n_res = await notify_handler_res.unwrap().execute(
        step_ctx,
        {
            "channel": "email",
            "template_id": "energy.grid_outage_restored",
            "recipient": "grid-ops@utility.example.com",
            "variables": {"meter_serial": "MTR-700"},
        },
    )
    assert n_res.is_ok
    envelope_id = n_res.unwrap()["envelope_id"]
    event_type = n_res.unwrap()["event_type"]
    outbox_stmt = select(IpDataPlaneOutboxRecord).where(
        IpDataPlaneOutboxRecord.tenant_id == seeded_ip_tenant,
        IpDataPlaneOutboxRecord.event_type == event_type,
    )
    outbox_rows = (await tenant_session.execute(outbox_stmt)).scalars().all()
    assert any(r.payload.get("id") == envelope_id for r in outbox_rows)


@pytest.mark.asyncio
async def test_postgres_stitch_repository_and_advisory_lock(
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    """Verifies Stitches persist in PostgreSQL (`ip.stitches`) and
    SqlAlchemyTokenRefreshLockAdapter acquires PostgreSQL `pg_advisory_xact_lock`.
    """
    container = Container()
    cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    wf_reg = container.workflow_definition_registry()
    stitch_cat = container.stitch_catalog()

    reg_uc = RegisterStitchUseCase(
        stitch_catalog=stitch_cat,
        definition_registry=wf_reg,
        uow=cp_uow,
    )
    reg_res = await reg_uc.execute(
        RegisterStitchCommand(
            tenant_id=seeded_ip_tenant,
            stitch_id="stitch_energy_custom_pg_01",
            workflow_id="energy.outage_restoration_stitch",
            workflow_version=1,
            canonical_event_type=EnergyEntityType.MDM_SERVICE_POINT.value,
            is_trigger=True,
            idempotency_key_field="service_point_external_id",
            concurrency_key_field="meter_serial_number",
        )
    )
    assert reg_res.is_ok
    assert reg_res.unwrap().id == "stitch_energy_custom_pg_01"

    # Query from a fresh InMemoryStitchCatalogRegistry + PostgreSQL Control Plane UoW
    fresh_cat = container.stitch_catalog()
    list_uc = ListStitchesUseCase(
        stitch_catalog=fresh_cat,
        uow=SqlAlchemyIpControlPlaneUnitOfWork(global_session),
    )
    listed = await list_uc.execute(ListStitchesQuery(tenant_id=seeded_ip_tenant))
    assert any(s.id == "stitch_energy_custom_pg_01" for s in listed)

    persisted = await cp_uow.stitches.get_by_id(
        tenant_id=seeded_ip_tenant,
        stitch_id="stitch_energy_custom_pg_01",
    )
    assert persisted is not None
    assert persisted.workflow_id == "energy.outage_restoration_stitch"
    assert persisted.canonical_event_type == EnergyEntityType.MDM_SERVICE_POINT.value

    cp_outbox_stmt = select(IpOutboxRecord).where(
        IpOutboxRecord.tenant_id == seeded_ip_tenant,
        IpOutboxRecord.event_type == IpEventType.STITCH_REGISTERED.value,
    )
    cp_outbox_rows = (await global_session.execute(cp_outbox_stmt)).scalars().all()
    assert any(r.payload.get("stitch_id") == "stitch_energy_custom_pg_01" for r in cp_outbox_rows)

    # Verify SqlAlchemyTokenRefreshLockAdapter with PostgreSQL pg_advisory_xact_lock
    lock_adapter = SqlAlchemyTokenRefreshLockAdapter(db_router=transactional_router)
    order: list[str] = []

    async def _worker(label: str) -> None:
        async with lock_adapter.acquire("conn_energy_oauth_01"):
            order.append(f"{label}_enter")
            await asyncio.sleep(0.01)
            order.append(f"{label}_exit")

    await asyncio.gather(_worker("w1"), _worker("w2"))
    assert order in (
        ["w1_enter", "w1_exit", "w2_enter", "w2_exit"],
        ["w2_enter", "w2_exit", "w1_enter", "w1_exit"],
    )
