"""Zero-mock unit tests for pure engine IpApiModule, LaunchableApiModule protocol, and IP API dependencies."""

from __future__ import annotations

import pytest
from database.router import DatabaseRouter
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_catalog_registry,
    get_cipher,
    get_connectors,
    get_inbound_ack,
    get_inbound_decoder,
    get_inbound_verifier,
    get_stitch_catalog_registry,
    get_tiered_storage,
    get_token_refresh_lock,
    get_token_refresher,
    get_transformer_registry,
    get_workflow_definition_registry,
    require_canonical_records_read,
    require_raw_records_read,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ErrorDetailHttpResponse,
    from_ip_error,
    to_error_response,
)
from ip.engine.domain.authorization import IpPermission, IpRole
from ip.engine.domain.exceptions import ConnectorNotFoundError
from ip.engine.module import IpApiModule
from seedwork.infra.api import LaunchableApiModule
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


def _make_request(app: FastAPI, identity: IdentityContext | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/tenants/ten_01/ip/connections",
        "headers": [],
        "app": app,
    }
    req = Request(scope)
    if identity is not None:
        req.state.identity = identity
    return req


@pytest.mark.asyncio
async def test_ip_api_module_registers_routes_with_lifecycle_hooks() -> None:
    module = IpApiModule()
    assert isinstance(module, LaunchableApiModule)
    assert module.name == "ip"

    app = FastAPI()
    module.register_routes(app)

    route_paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
    assert "/api/v1/tenants/{tenant_id}/ip/catalog/apps" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/catalog/apps/{app_id}/spec" in route_paths

    catalog_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path
        in {
            "/api/v1/tenants/{tenant_id}/ip/catalog/apps",
            "/api/v1/tenants/{tenant_id}/ip/catalog/apps/{app_id}/spec",
        }
    ]
    assert len(catalog_routes) == 2
    for catalog_route in catalog_routes:
        dep_calls = {dep.call for dep in catalog_route.dependant.dependencies}
        assert require_tenant_member in dep_calls
    assert "/api/v1/tenants/{tenant_id}/ip/connections" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/traces/{trace_id}" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/transformations/transformers" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/transformations/preview" in route_paths
    assert (
        "/api/v1/tenants/{tenant_id}/ip/transformations/connections/{connection_id}/streams/{stream}"
        in route_paths
    )
    assert "/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/sync-runs" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/streams/state" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/stitches/definitions" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/stitches" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/stitches/dispatch" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/stitches/runs/{run_id}" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/records/normalized" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/records/gem" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/records/replica" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/records/inbound" in route_paths

    router = DatabaseRouter(global_db_url="postgresql+asyncpg://localhost:5432/test")
    await module.startup(app, router)
    assert app.state.ip_container is not None
    assert app.state.ip_tenant_resolver is not None

    await module.shutdown(app)
    await router.close_all()
    assert app.state.ip_container is None
    assert app.state.ip_tenant_resolver is None


@pytest.mark.asyncio
async def test_require_tenant_member_rejects_unauthenticated_requests() -> None:
    app = FastAPI()
    IpApiModule().register_routes(app)
    session = AsyncSession()
    unauth_req = _make_request(app, identity=None)

    with pytest.raises(HTTPException) as exc_info:
        await require_tenant_member(
            request=unauth_req,
            session=session,
            tenant_id="ten_01",
        )
    assert exc_info.value.status_code == 401
    await session.close()


@pytest.mark.asyncio
async def test_require_tenant_member_validates_tenant_scope() -> None:
    app = FastAPI()
    IpApiModule().register_routes(app)
    session = AsyncSession()
    member_identity = IdentityContext(
        subject="usr_01",
        claims={},
        tenant_id="ten_01",
        authorized_tenants={"ten_01"},
        tenant_mapping={"org_01": "ten_01"},
    )
    member_req = _make_request(app, identity=member_identity)
    resolved = await require_tenant_member(
        request=member_req,
        session=session,
        tenant_id="ten_01",
    )
    assert resolved.subject == "usr_01"
    assert member_req.state.ucp_tenant_id == "ten_01"

    other_req = _make_request(app, identity=member_identity)
    with pytest.raises(HTTPException) as forbidden_exc:
        await require_tenant_member(
            request=other_req,
            session=session,
            tenant_id="ten_unauthorized",
        )
    assert forbidden_exc.value.status_code == 403
    assert PLATFORM_TENANT_ID not in member_identity.authorized_tenants
    await session.close()


@pytest.mark.asyncio
async def test_ip_permission_rbac_enforcement() -> None:
    support_identity = IdentityContext(
        subject="usr_support",
        claims={},
        tenant_id="ten_01",
        authorized_tenants={"ten_01"},
        roles=(IpRole.CUSTOMER_SUPPORT.value,),
        tenant_roles={"ten_01": (IpRole.CUSTOMER_SUPPORT.value,)},
    )
    res_canon = await require_canonical_records_read(identity=support_identity, tenant_id="ten_01")
    assert res_canon.subject == "usr_support"

    res_raw = await require_raw_records_read(identity=support_identity, tenant_id="ten_01")
    assert res_raw.subject == "usr_support"

    customer_identity = IdentityContext(
        subject="usr_customer",
        claims={},
        tenant_id="ten_01",
        authorized_tenants={"ten_01"},
        roles=(IpRole.CUSTOMER.value,),
        tenant_roles={"ten_01": (IpRole.CUSTOMER.value,)},
    )
    customer_canon = await require_canonical_records_read(
        identity=customer_identity, tenant_id="ten_01"
    )
    assert customer_canon.subject == "usr_customer"

    with pytest.raises(HTTPException) as exc_info:
        await require_raw_records_read(identity=customer_identity, tenant_id="ten_01")
    assert exc_info.value.status_code == 403
    assert IpPermission.IP_RECORDS_RAW_READ.value in exc_info.value.detail

    with pytest.raises(HTTPException) as cross_exc:
        await require_canonical_records_read(identity=customer_identity, tenant_id="ten_other")
    assert cross_exc.value.status_code == 403

    direct_perm_identity = IdentityContext(
        subject="usr_custom_agent",
        claims={},
        tenant_id="ten_01",
        authorized_tenants={"ten_01"},
        permissions=(IpPermission.IP_RECORDS_RAW_READ.value,),
    )
    direct_res = await require_raw_records_read(identity=direct_perm_identity, tenant_id="ten_01")
    assert direct_res.subject == "usr_custom_agent"


def test_pure_engine_api_dependencies_expose_protocol_only_defaults() -> None:
    app = FastAPI()
    IpApiModule().register_routes(app)
    req = _make_request(app)

    registry = get_catalog_registry(req)
    connectors = get_connectors(registry)
    assert set(connectors) == {"http", "sftp"}
    assert connectors["http"] is not None
    with pytest.raises(KeyError):
        _ = connectors["non_existent_connector"]

    assert get_cipher(req) is not None
    assert get_tiered_storage(req) is not None
    assert get_inbound_verifier(req) is not None
    assert get_inbound_decoder(req) is not None
    assert get_inbound_ack(req) is not None
    assert get_token_refresh_lock(req) is get_token_refresh_lock(req)
    assert get_token_refresher(req) is get_token_refresher(req)

    transformer_reg = get_transformer_registry(req)
    assert transformer_reg is get_transformer_registry(req)
    assert transformer_reg.list_transformers() == ()

    wf_reg = get_workflow_definition_registry(req)
    assert wf_reg is get_workflow_definition_registry(req)
    assert wf_reg.list_definitions() == ()

    stitch_cat = get_stitch_catalog_registry(req)
    assert stitch_cat is get_stitch_catalog_registry(req)
    assert stitch_cat.list_stitches(tenant_id="*") == ()


def test_ip_error_dto_responses_map_domain_errors_to_http_status() -> None:
    err_resp = to_error_response(
        status_code=400,
        code="BAD_INPUT",
        message="Invalid field",
        details=[ErrorDetailHttpResponse(field="name", code="REQUIRED", message="Required")],
        trace_id="ip_trc_01",
    )
    assert err_resp.status_code == 400

    ip_err_resp = from_ip_error(ConnectorNotFoundError.for_app("unknown_app"), trace_id="ip_trc_02")
    assert ip_err_resp.status_code == 404
