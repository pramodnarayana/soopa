"""Zero-mock unit tests for IpApiModule, LaunchableApiModule protocol, and IP API dependencies."""

from __future__ import annotations

import pytest
from database.router import DatabaseRouter
from fastapi import FastAPI, HTTPException
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
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ErrorDetailHttpResponse,
    from_ip_error,
    to_error_response,
)
from ip.engine.adapters.inbound.api.module import IpApiModule
from ip.engine.domain.exceptions import ConnectorNotFoundError
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
async def test_ip_api_module_implements_launchable_api_module_and_registers_routes() -> None:
    module = IpApiModule()
    assert isinstance(module, LaunchableApiModule)
    assert module.name == "ip"

    app = FastAPI()
    module.register_routes(app)

    route_paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/ip/catalog/apps" in route_paths
    assert "/api/v1/ip/catalog/apps/{app_id}/spec" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/connections" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/transactions/{trace_id}" in route_paths
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

    router = DatabaseRouter(global_db_url="postgresql+asyncpg://localhost:5432/test")
    await module.startup(app, router)
    assert app.state.ip_container is not None
    assert app.state.ip_tenant_resolver is not None

    await module.shutdown(app)
    await router.close_all()
    assert app.state.ip_container is None
    assert app.state.ip_tenant_resolver is None


@pytest.mark.asyncio
async def test_require_tenant_member_enforces_authentication_and_tenant_scope() -> None:
    app = FastAPI()
    session = AsyncSession()
    unauth_req = _make_request(app, identity=None)

    with pytest.raises(HTTPException) as exc_info:
        await require_tenant_member(
            request=unauth_req,
            session=session,
            tenant_id="ten_01",
        )
    assert exc_info.value.status_code == 401

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


def test_ip_api_dependencies_and_error_dtos() -> None:
    app = FastAPI()
    req = _make_request(app)

    registry = get_catalog_registry()
    connectors = get_connectors(registry)
    assert len(connectors) >= 6
    assert "http" in list(connectors)
    assert connectors["http"] is not None
    with pytest.raises(KeyError):
        _ = connectors["non_existent_connector"]

    assert get_cipher() is not None
    assert get_tiered_storage() is not None
    assert get_inbound_verifier() is not None
    assert get_inbound_decoder() is not None
    assert get_inbound_ack() is not None
    assert get_token_refresh_lock(req) is get_token_refresh_lock(req)
    assert get_token_refresher(req) is get_token_refresher(req)

    transformer_reg = get_transformer_registry(req)
    assert transformer_reg is get_transformer_registry(req)
    assert len(transformer_reg.list_transformers()) >= 6

    wf_reg = get_workflow_definition_registry(req)
    assert wf_reg is get_workflow_definition_registry(req)
    assert len(wf_reg.list_definitions()) >= 3

    stitch_cat = get_stitch_catalog_registry(req)
    assert stitch_cat is get_stitch_catalog_registry(req)
    assert len(stitch_cat.list_stitches(tenant_id="*")) >= 2

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
