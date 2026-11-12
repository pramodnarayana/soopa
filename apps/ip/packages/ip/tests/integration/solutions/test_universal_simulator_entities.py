"""SAVEPOINT narrow integration tests for connection-scoped Universal Simulator Entities (`ip.simulator_entities`)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from database.models.identity import Tenant as TenantORM
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from identity.domain.authorization import StandardRole
from identity.domain.constants import IdentityIdPrefix
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_cipher,
    get_ip_global_session,
    require_tenant_member,
)
from ip.engine.adapters.outbound.database.models.data_plane import InboundRecordModel
from ip.module import IpApiModule
from ip.solutions.connectors.sandbox.universal.models import SimulatorEntityRecord
from security.provider import SecurityProvider
from seedwork import generate_id
from sqlalchemy import select
from ucp.domain.constants import LifecycleStatus

pytestmark = pytest.mark.integration

_TEST_KEY_BYTES = b"0123456789abcdef0123456789abcdef"


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
    app.dependency_overrides[get_cipher] = lambda: cipher
    return app


@pytest.mark.asyncio
async def test_simulator_connection_entity_lifecycle_persists_push_records(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    admin_ctx = IdentityContext(
        subject="usr_sim_admin",
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Pre-flight Check (`NO_AUTH`)
        check_ok = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/check",
            json={
                "app_id": "universal_simulator",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 42, "records_per_pull": 25},
                "raw_credentials": {},
            },
        )
        assert check_ok.status_code == 200
        assert check_ok.json()["success"] is True

        # 2. Create Simulator Connection (`NO_AUTH`)
        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "ERP Simulator Connection",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 42, "records_per_pull": 25},
                "raw_credentials": {},
                "endpoint_for_fingerprint": "ERP Simulator Connection",
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]

        # 3. Discover before any entities exist -> 200 OK with empty streams
        empty_disc_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/discover"
        )
        assert empty_disc_resp.status_code == 200
        assert empty_disc_resp.json()["streams"] == []

        # 4. Create Entity inside the Simulator Connection
        ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "purchase_orders",
                "sample_blueprint": {
                    "po_id": "PO-10001",
                    "vendor_email": "ops@vendor.example",
                    "amount": 1250.75,
                    "updated_at": "2026-06-01T00:00:00Z",
                },
                "records_per_pull": 15,
            },
        )
        assert ent_resp.status_code == 201
        ent_body = ent_resp.json()
        entity_id = ent_body["id"]
        assert entity_id.startswith("sim_ent_")
        assert ent_body["connection_id"] == connection_id
        assert ent_body["primary_key_field"] == "po_id"
        assert ent_body["version"] == 1

        # 5. PATCH Entity to verify schema re-inference, TIMESERIES_COLUMNAR wire contract, version bump
        patch_resp = await client.patch(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities/{entity_id}",
            json={
                "records_per_pull": 30,
                "velocity_mode": "TIMESERIES_COLUMNAR",
                "sample_blueprint": {
                    "po_id": "PO-10001",
                    "vendor_email": "ops@vendor.example",
                    "amount": 1250.75,
                    "currency": "USD",
                    "updated_at": "2026-06-01T00:00:00Z",
                },
            },
        )
        assert patch_resp.status_code == 200
        patched_body = patch_resp.json()
        assert patched_body["version"] == 2
        assert patched_body["records_per_pull"] == 30
        assert patched_body["velocity_mode"] == "TIMESERIES_COLUMNAR"
        assert "currency" in patched_body["inferred_json_schema"]["properties"]

        # 6. Discover Entities -> returns `purchase_orders`
        disc_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/discover"
        )
        assert disc_resp.status_code == 200
        disc_body = disc_resp.json()
        assert [s["name"] for s in disc_body["streams"]] == ["purchase_orders"]

        # 7. Trigger Simulated Push (`POST /connections/{id}/simulate-push`) -> persists L1 inbound_records on ip_shard
        push_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulate-push",
            json={
                "stream_name": "purchase_orders",
                "count": 3,
                "delivery_style": "FULL_PAYLOAD",
            },
        )
        assert push_resp.status_code == 202
        push_body = push_resp.json()
        assert push_body["records_pushed"] == 3
        assert push_body["status"] == "ACCEPTED"
        assert len(push_body["record_ids"]) == 3

        persisted_rows = (
            (
                await tenant_session.execute(
                    select(InboundRecordModel).where(
                        InboundRecordModel.tenant_id == seeded_ip_tenant,
                        InboundRecordModel.connection_id == connection_id,
                        InboundRecordModel.stream_name == "purchase_orders",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(persisted_rows) == 3

        # 8. Permanently deleting Connection cascades to its `ip.simulator_entities`
        del_conn_resp = await client.delete(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}?permanent=true"
        )
        assert del_conn_resp.status_code == 204

        remaining_entities = (
            (
                await global_session.execute(
                    select(SimulatorEntityRecord).where(
                        SimulatorEntityRecord.connection_id == connection_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining_entities) == 0


@pytest.mark.asyncio
async def test_simulator_duplicate_entity_conflict_recovers_via_savepoint(
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    admin_ctx = IdentityContext(
        subject="usr_sim_admin",
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "NetSuite Simulator",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 42},
                "raw_credentials": {},
                "endpoint_for_fingerprint": "NetSuite Simulator",
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]

        ent_ok = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "customers",
                "sample_blueprint": {"customer_id": "CUST-01", "email": "a@b.org"},
            },
        )
        assert ent_ok.status_code == 201

        dup_ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "customers",
                "sample_blueprint": {"customer_id": "CUST-02", "email": "c@d.org"},
            },
        )
        assert dup_ent_resp.status_code == 409

        list_after_conflict = await client.get(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities"
        )
        assert list_after_conflict.status_code == 200
        assert len(list_after_conflict.json()) == 1


@pytest.mark.asyncio
async def test_simulator_enforces_cross_tenant_connection_isolation(
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    other_tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    other_tenant = TenantORM(
        id=other_tenant_id,
        name="Secondary Isolated Tenant",
        slug=f"ip-other-{other_tenant_id[-8:]}",
        status=LifecycleStatus.ACTIVE,
    )
    global_session.add(other_tenant)
    await global_session.flush()

    admin_ctx = IdentityContext(
        subject="usr_sim_admin",
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "Tenant Alpha Private Simulator",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 42},
                "raw_credentials": {},
                "endpoint_for_fingerprint": "Tenant Alpha Private Simulator",
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]

        ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "invoices",
                "sample_blueprint": {"invoice_id": "INV-01"},
            },
        )
        assert ent_resp.status_code == 201
        entity_id = ent_resp.json()["id"]

        active_identity["current"] = IdentityContext(
            subject="usr_other_admin",
            claims={},
            tenant_id=other_tenant_id,
            authorized_tenants={other_tenant_id},
            roles=(StandardRole.TENANT_ADMIN.value,),
        )
        cross_get = await client.get(
            f"/api/v1/tenants/{other_tenant_id}/ip/connections/{connection_id}/simulator/entities"
        )
        assert cross_get.status_code == 404

        cross_del = await client.delete(
            f"/api/v1/tenants/{other_tenant_id}/ip/connections/{connection_id}/simulator/entities/{entity_id}"
        )
        assert cross_del.status_code == 404


@pytest.mark.asyncio
async def test_simulator_enforces_granular_rbac_permissions(
    global_session: GlobalSession,
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    admin_ctx = IdentityContext(
        subject="usr_sim_admin",
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "RBAC Controlled Simulator",
                "auth_type": "NO_AUTH",
                "public_config": {"seed": 42},
                "raw_credentials": {},
                "endpoint_for_fingerprint": "RBAC Controlled Simulator",
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]

        active_identity["current"] = IdentityContext(
            subject="usr_customer_ro",
            claims={},
            tenant_id=seeded_ip_tenant,
            authorized_tenants={seeded_ip_tenant},
            roles=(StandardRole.CUSTOMER.value,),
        )
        customer_list = await client.get(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities"
        )
        assert customer_list.status_code == 200
        assert customer_list.json() == []

        customer_post = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities",
            json={
                "entity_name": "unauthorized_stream",
                "sample_blueprint": {"id": "REC-1"},
            },
        )
        assert customer_post.status_code == 403

        customer_push = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulate-push",
            json={"stream_name": "customers", "count": 1},
        )
        assert customer_push.status_code == 403

        active_identity["current"] = IdentityContext(
            subject="usr_viewer",
            claims={},
            tenant_id=seeded_ip_tenant,
            authorized_tenants={seeded_ip_tenant},
            roles=(StandardRole.VIEWER.value,),
        )
        viewer_get = await client.get(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/simulator/entities"
        )
        assert viewer_get.status_code == 403
