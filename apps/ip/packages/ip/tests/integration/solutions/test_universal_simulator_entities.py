"""SAVEPOINT narrow integration tests for Universal Simulator Virtual Sandboxes (`ip.simulator_sandboxes` & `ip.simulator_entities`)."""

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
async def test_sandbox_connection_lifecycle_persists_simulated_push_records(
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
        # 1. Provision Virtual Sandbox
        sbx_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes",
            json={"name": "Integration ERP Sandbox"},
        )
        assert sbx_resp.status_code == 201
        sbx_body = sbx_resp.json()
        sandbox_id = sbx_body["id"]
        api_key = sbx_body["api_key"]
        assert sandbox_id.startswith("sbx_")
        assert api_key.startswith("sbx_key_")

        # 2. Configure Entity inside the Virtual Sandbox
        ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}/entities",
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
        assert ent_body["primary_key_field"] == "po_id"
        assert ent_body["version"] == 1

        # 3. PATCH Entity to verify schema re-inference, TIMESERIES_COLUMNAR wire contract, and version bump
        patch_resp = await client.patch(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}/entities/{entity_id}",
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

        # 4. Pre-flight Check via Component 1 (`POST /connections/check`)
        check_bad = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/check",
            json={
                "app_id": "universal_simulator",
                "auth_type": "API_KEY",
                "public_config": {"sandbox_id": sandbox_id, "seed": 42},
                "raw_credentials": {"api_key": "sbx_key_invalid"},
            },
        )
        assert check_bad.status_code == 200
        assert check_bad.json()["success"] is False

        check_ok = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/check",
            json={
                "app_id": "universal_simulator",
                "auth_type": "API_KEY",
                "public_config": {"sandbox_id": sandbox_id, "seed": 42},
                "raw_credentials": {"api_key": api_key},
            },
        )
        assert check_ok.status_code == 200
        assert check_ok.json()["success"] is True

        # 5. Create Connection in Component 1 (`POST /connections`)
        conn_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections",
            json={
                "app_id": "universal_simulator",
                "name": "ERP Sandbox Connection",
                "auth_type": "API_KEY",
                "public_config": {"sandbox_id": sandbox_id, "seed": 42},
                "raw_credentials": {"api_key": api_key},
                "endpoint_for_fingerprint": sandbox_id,
            },
        )
        assert conn_resp.status_code == 201
        connection_id = conn_resp.json()["id"]
        assert "streams" not in conn_resp.json()["public_config"]

        # 6. Discover Entities via Component 2 (`POST /connections/{id}/discover`)
        disc_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}/discover"
        )
        assert disc_resp.status_code == 200
        disc_body = disc_resp.json()
        assert disc_body["catalog_version"] == 1
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

        # 8. Deleting Connection does NOT delete the decoupled Virtual Sandbox or its Entities
        del_conn_resp = await client.delete(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/{connection_id}?permanent=true"
        )
        assert del_conn_resp.status_code == 204

        list_ent_resp = await client.get(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}/entities"
        )
        assert list_ent_resp.status_code == 200
        assert len(list_ent_resp.json()) == 1

        # 9. Deleting Virtual Sandbox cascades to its Entities
        del_sbx_resp = await client.delete(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}"
        )
        assert del_sbx_resp.status_code == 204


@pytest.mark.asyncio
async def test_simulator_duplicate_conflicts_recover_via_savepoint(
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
        sbx_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes",
            json={"name": "NetSuite ERP Sandbox"},
        )
        assert sbx_resp.status_code == 201
        sandbox_id = sbx_resp.json()["id"]

        dup_sbx_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes",
            json={"name": "NetSuite ERP Sandbox"},
        )
        assert dup_sbx_resp.status_code == 409

        ent_ok = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}/entities",
            json={
                "entity_name": "customers",
                "sample_blueprint": {"customer_id": "CUST-01", "email": "a@b.org"},
            },
        )
        assert ent_ok.status_code == 201

        dup_ent_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}/entities",
            json={
                "entity_name": "customers",
                "sample_blueprint": {"customer_id": "CUST-02", "email": "c@d.org"},
            },
        )
        assert dup_ent_resp.status_code == 409

        list_after_conflict = await client.get(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes/{sandbox_id}/entities"
        )
        assert list_after_conflict.status_code == 200
        assert len(list_after_conflict.json()) == 1


@pytest.mark.asyncio
async def test_simulator_enforces_cross_tenant_sandbox_isolation(
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
        sbx_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes",
            json={"name": "Tenant Alpha Private Sandbox"},
        )
        assert sbx_resp.status_code == 201
        sandbox_id = sbx_resp.json()["id"]

        active_identity["current"] = IdentityContext(
            subject="usr_other_admin",
            claims={},
            tenant_id=other_tenant_id,
            authorized_tenants={other_tenant_id},
            roles=(StandardRole.TENANT_ADMIN.value,),
        )
        cross_get = await client.get(
            f"/api/v1/tenants/{other_tenant_id}/ip/simulator/sandboxes/{sandbox_id}"
        )
        assert cross_get.status_code == 404

        cross_del = await client.delete(
            f"/api/v1/tenants/{other_tenant_id}/ip/simulator/sandboxes/{sandbox_id}"
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
        sbx_resp = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes",
            json={"name": "RBAC Controlled Sandbox"},
        )
        assert sbx_resp.status_code == 201

        active_identity["current"] = IdentityContext(
            subject="usr_customer_ro",
            claims={},
            tenant_id=seeded_ip_tenant,
            authorized_tenants={seeded_ip_tenant},
            roles=(StandardRole.CUSTOMER.value,),
        )
        customer_list = await client.get(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes"
        )
        assert customer_list.status_code == 200
        assert len(customer_list.json()) == 1

        customer_post = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes",
            json={"name": "Unauthorized Customer Sandbox"},
        )
        assert customer_post.status_code == 403

        customer_push = await client.post(
            f"/api/v1/tenants/{seeded_ip_tenant}/ip/connections/conn_fake/simulate-push",
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
        viewer_get = await client.get(f"/api/v1/tenants/{seeded_ip_tenant}/ip/simulator/sandboxes")
        assert viewer_get.status_code == 403
