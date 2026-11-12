"""Unit tests for the outer IP Solution IoC composition root (`ip.solutions.bootstrap` & `ip.module`)."""

from __future__ import annotations

from fastapi import FastAPI
from ip.engine.adapters.inbound.api.dependencies import (
    get_catalog_registry,
    get_connectors,
    get_stitch_catalog_registry,
    get_transformer_registry,
    get_workflow_definition_registry,
)
from ip.engine.bootstrap.container import Container
from ip.module import IpApiModule
from ip.solutions.bootstrap import (
    configure_solution_container,
    create_solution_api_provider,
)
from starlette.requests import Request


def _make_request(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/tenants/ten_01/ip/connections",
            "headers": [],
            "app": app,
        }
    )


def test_solution_bootstrap_injects_vertical_plugins_into_container() -> None:
    container = Container()
    container.config.allow_private_ips.from_value(False)
    configure_solution_container(container)

    catalog = container.catalog_registry()
    app_ids = {summary.app_id for summary in catalog.list_apps()}
    assert {
        "http",
        "sftp",
        "salesforce",
        "universal_simulator",
    }.issubset(app_ids)
    assert len(container.transformer_registry().list_transformers()) >= 6
    assert len(container.workflow_definition_registry().list_definitions()) >= 3
    assert len(container.stitch_catalog().list_stitches(tenant_id="ten_1")) >= 2


def test_solution_api_provider_wires_builtin_solution_registries() -> None:
    provider = create_solution_api_provider()
    app_ids = {s.app_id for s in provider.get_catalog_registry().list_apps()}
    assert {
        "http",
        "sftp",
        "salesforce",
        "universal_simulator",
    }.issubset(app_ids)
    assert len(provider.create_transformer_registry().list_transformers()) >= 6


def test_outer_ip_api_module_exposes_registered_solution_plugins() -> None:
    app = FastAPI()
    IpApiModule().register_routes(app)
    req = _make_request(app)

    connectors = get_connectors(get_catalog_registry(req))
    assert len(connectors) >= 6
    assert "http" in list(connectors)
    assert len(get_transformer_registry(req).list_transformers()) >= 6
    assert len(get_workflow_definition_registry(req).list_definitions()) >= 3
    assert len(get_stitch_catalog_registry(req).list_stitches(tenant_id="*")) >= 2
