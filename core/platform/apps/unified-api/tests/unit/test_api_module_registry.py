"""Unit tests for dynamic ENABLED_APPS API module registry and isolated shell creation."""

from __future__ import annotations

import pytest
from starlette.routing import Mount

from unified_api.main import create_app
from unified_api.registry import (
    get_api_module_instance,
    load_enabled_api_modules,
    parse_enabled_app_names,
)


def test_parse_enabled_app_names_orders_inline_modules_before_root_mount() -> None:
    assert parse_enabled_app_names("edi,ip") == ("ip", "edi")
    assert parse_enabled_app_names("ip,edi") == ("ip", "edi")
    assert parse_enabled_app_names("ip") == ("ip",)
    assert parse_enabled_app_names("edi") == ("edi",)
    assert parse_enabled_app_names("platform,ip") == ("ip",)
    assert parse_enabled_app_names("") == ()

    with pytest.raises(ValueError, match="Unknown API module"):
        parse_enabled_app_names("ip,unknown_app")

    with pytest.raises(ValueError, match="Unknown API module"):
        get_api_module_instance("unknown_app")


def test_create_app_ip_only_mode_excludes_edi_sub_app() -> None:
    ip_only_app = create_app(enabled_apps="ip")
    module_names = [m.name for m in ip_only_app.state.api_modules]
    assert module_names == ["ip"]
    assert not hasattr(ip_only_app.state, "edi_app")

    # Verify no root Mount("/") from EDI exists
    mounts = [r for r in ip_only_app.routes if isinstance(r, Mount) and r.path == ""]
    assert mounts == []

    # Verify IP routes and Core Platform routes are registered
    route_paths = {getattr(r, "path", "") for r in ip_only_app.routes}
    assert "/health" in route_paths
    assert "/api/v1/ip/catalog/apps" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/connections" in route_paths
    assert "/api/v1/tenants" in route_paths


def test_create_app_edi_only_mode_excludes_ip_routes() -> None:
    edi_only_app = create_app(enabled_apps="edi")
    module_names = [m.name for m in edi_only_app.state.api_modules]
    assert module_names == ["edi"]
    assert edi_only_app.state.edi_app is not None

    route_paths = {getattr(r, "path", "") for r in edi_only_app.routes}
    assert "/health" in route_paths
    assert "/api/v1/ip/catalog/apps" not in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/connections" not in route_paths


def test_create_app_multi_app_mode_mounts_both_ip_and_edi() -> None:
    both_app = create_app(enabled_apps="edi,ip")
    module_names = [m.name for m in load_enabled_api_modules("edi,ip")]
    assert module_names == ["ip", "edi"]
    assert both_app.state.edi_app is not None

    route_paths = {getattr(r, "path", "") for r in both_app.routes}
    assert "/health" in route_paths
    assert "/api/v1/ip/catalog/apps" in route_paths
    assert "/api/v1/tenants/{tenant_id}/ip/connections" in route_paths
