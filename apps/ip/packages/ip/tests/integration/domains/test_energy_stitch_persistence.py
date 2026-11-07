"""Narrow PostgreSQL Integration Tests for Control Plane Stitch Persistence and Advisory Token Refresh Locks."""

from __future__ import annotations

import asyncio

import pytest
from database.testing import TransactionalTestRouter
from database.types import GlobalSession
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    SqlAlchemyTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.application.use_cases.stitch.stitch_control_plane_use_cases import (
    ListStitchesQuery,
    ListStitchesUseCase,
    RegisterStitchCommand,
    RegisterStitchUseCase,
)
from ip.engine.bootstrap.container import Container, create_ip_control_plane_uow
from ip.engine.domain.enums import IpEventType
from ip.solutions.bootstrap import configure_solution_container
from ip.solutions.domains.energy.canonical import EnergyEntityType
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_stitch_repository_persists_tenant_stitches_with_outbox_events(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies Stitches persist in PostgreSQL (`ip.stitches`) and stage STITCH_REGISTERED outbox events."""
    container = configure_solution_container(Container())
    cp_uow = create_ip_control_plane_uow(global_session)
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

    fresh_cat = container.stitch_catalog()
    list_uc = ListStitchesUseCase(
        stitch_catalog=fresh_cat,
        uow=create_ip_control_plane_uow(global_session),
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


@pytest.mark.asyncio
async def test_postgres_stitch_repository_supports_wildcard_override_with_conflict_protection(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies wildcard stitch override priority and cross-tenant 409 collision protection in PostgreSQL."""
    container = configure_solution_container(Container())
    cp_uow = create_ip_control_plane_uow(global_session)
    reg_uc = RegisterStitchUseCase(
        stitch_catalog=container.stitch_catalog(),
        definition_registry=container.workflow_definition_registry(),
        uow=cp_uow,
    )

    reg_wildcard_res = await reg_uc.execute(
        RegisterStitchCommand(
            tenant_id="*",
            stitch_id="stitch_shared_override_test",
            workflow_id="energy.outage_restoration_stitch",
            workflow_version=1,
            canonical_event_type=EnergyEntityType.MDM_SERVICE_POINT.value,
            is_trigger=True,
        )
    )
    assert reg_wildcard_res.is_ok

    reg_override_res = await reg_uc.execute(
        RegisterStitchCommand(
            tenant_id=seeded_ip_tenant,
            stitch_id="stitch_shared_override_test",
            workflow_id="energy.outage_restoration_stitch",
            workflow_version=1,
            canonical_event_type=EnergyEntityType.MDM_SERVICE_POINT.value,
            is_trigger=True,
        )
    )
    assert reg_override_res.is_ok

    persisted_override = await cp_uow.stitches.get_by_id(
        tenant_id=seeded_ip_tenant,
        stitch_id="stitch_shared_override_test",
    )
    assert persisted_override is not None
    assert persisted_override.tenant_id == seeded_ip_tenant

    reg_conflict_res = await reg_uc.execute(
        RegisterStitchCommand(
            tenant_id="other_concrete_tenant_999",
            stitch_id="stitch_shared_override_test",
            workflow_id="energy.outage_restoration_stitch",
            workflow_version=1,
            canonical_event_type=EnergyEntityType.MDM_SERVICE_POINT.value,
            is_trigger=True,
        )
    )
    assert reg_conflict_res.is_err
    assert reg_conflict_res.unwrap_err().http_status == 409


@pytest.mark.asyncio
async def test_postgres_token_refresh_lock_adapter_serializes_concurrent_workers(
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verifies SqlAlchemyTokenRefreshLockAdapter acquires PostgreSQL `pg_advisory_xact_lock`."""
    lock_adapter_1 = SqlAlchemyTokenRefreshLockAdapter(db_router=transactional_router)
    lock_adapter_2 = SqlAlchemyTokenRefreshLockAdapter(db_router=transactional_router)
    order: list[str] = []

    async def _worker(adapter: SqlAlchemyTokenRefreshLockAdapter, label: str) -> None:
        async with adapter.acquire("conn_energy_oauth_01"):
            order.append(f"{label}_enter")
            await asyncio.sleep(0.01)
            order.append(f"{label}_exit")

    await asyncio.gather(_worker(lock_adapter_1, "w1"), _worker(lock_adapter_2, "w2"))
    assert order in (
        ["w1_enter", "w1_exit", "w2_enter", "w2_exit"],
        ["w2_enter", "w2_exit", "w1_enter", "w1_exit"],
    )
