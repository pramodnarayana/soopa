"""Unit tests for ConnectorCatalogRegistry."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager

import pytest
from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.bootstrap.container import Container
from ip.engine.domain.connection.catalog import ConnectorPropertySchema
from ip.engine.domain.connection.http_spec import DeclarativeManifest, HttpActionSpec
from ip.engine.domain.exceptions import ConnectorNotFoundError, Result, TenantShardNotFoundError
from ip.engine.ports.outbound.catalog_registry_port import CatalogConnectorMapping
from ip.engine.ports.outbound.uow import IpTenantResolverPort


@pytest.mark.asyncio
async def test_generic_registry_registration_and_unregistration() -> None:
    registry = ConnectorCatalogRegistry(auth_resolver=AuthStrategyResolver())
    assert len(registry.list_apps()) == 0

    schema = ConnectorPropertySchema(
        app_id="custom_crm",
        display_name="Custom Enterprise CRM",
        auth_type="API_KEY",
        category="CRM",
        description="Dynamic custom connector",
        properties=(),
    )
    manifest = DeclarativeManifest(
        app_id="custom_crm",
        display_name="Custom Enterprise CRM",
        category="CRM",
        auth_type="API_KEY",
        base_url_template="https://api.custom.com",
        property_schema=schema,
        check_action=HttpActionSpec(path="/ping", method="GET"),
        streams={},
    )
    registry.register_manifest(manifest)
    assert len(registry.list_apps()) == 1
    spec_res = registry.get_app_spec("custom_crm")
    assert spec_res.is_ok is True
    assert spec_res.value is not None
    assert spec_res.value.display_name == "Custom Enterprise CRM"

    connector_res = registry.get_connector("custom_crm")
    assert connector_res.is_ok is True
    assert connector_res.value is not None
    assert connector_res.value.app_id == "custom_crm"

    registry.unregister("custom_crm")
    assert len(registry.list_apps()) == 0
    missing_res = registry.get_connector("custom_crm")
    assert missing_res.is_err is True
    assert isinstance(missing_res.error, ConnectorNotFoundError)


class _StubRouter(DatabaseRouterPort):
    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        raise NotImplementedError
        yield

    @asynccontextmanager
    async def global_session_scope(self) -> AsyncIterator[GlobalSession]:
        raise NotImplementedError
        yield

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        _ = (tenant_id, shard_key, shard_url)
        raise NotImplementedError
        yield

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        _ = (shard_key, shard_url)
        raise NotImplementedError
        yield

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        _ = app_slug
        return []

    async def close_all(self) -> None:
        return None


class _StubTenantResolver(IpTenantResolverPort):
    async def get_all_tenant_ids(self) -> list[str]:
        return []

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        _ = tenant_id
        return ("shard_01", "postgresql+asyncpg://localhost/ip")

    async def resolve_tenant_shard(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        _ = tenant_id
        return Result.ok(("shard_01", "postgresql+asyncpg://localhost/ip"))


def test_catalog_connector_mapping_and_container_wiring() -> None:
    registry = ConnectorCatalogRegistry(auth_resolver=AuthStrategyResolver())
    schema = ConnectorPropertySchema(
        app_id="custom_crm",
        display_name="Custom CRM",
        auth_type="API_KEY",
        category="CRM",
        description="Dynamic CRM",
        properties=(),
    )
    registry.register_manifest(
        DeclarativeManifest(
            app_id="custom_crm",
            display_name="Custom CRM",
            category="CRM",
            auth_type="API_KEY",
            base_url_template="https://api.custom.com",
            property_schema=schema,
            check_action=HttpActionSpec(path="/ping", method="GET"),
            streams={},
        )
    )

    mapping = CatalogConnectorMapping(registry)
    assert isinstance(mapping, Mapping)
    assert len(mapping) == 1
    assert list(mapping) == ["custom_crm"]
    assert "custom_crm" in mapping
    assert "missing_app" not in mapping
    resolved = mapping.get("custom_crm")
    assert resolved is not None
    assert resolved.app_id == "custom_crm"
    assert mapping.get("missing_app") is None

    container = Container(
        db_router=_StubRouter(),
        tenant_resolver=_StubTenantResolver(),
    )
    container.config.allow_private_ips.from_value(True)

    consumers = (
        container.discover_catalog_use_case(uow=object(), token_manager=object()),
        container.fetch_record_use_case(control_plane_uow=object(), token_manager=object()),
        container.run_sync_use_case(control_plane_uow=object(), token_manager=object()),
        container.deliver_outbound_record_use_case(token_manager=object()),
        container.session_scoped_outbound_delivery(),
    )
    for consumer in consumers:
        connectors = consumer._connectors
        assert isinstance(connectors, Mapping)
        http_connector = connectors.get("http")
        assert http_connector is not None
        assert http_connector.app_id == "http"
        assert connectors.get("nonexistent_app_id") is None
