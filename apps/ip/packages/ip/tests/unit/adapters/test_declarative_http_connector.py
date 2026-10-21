"""Unit tests for DeclarativeHttpConnector engine."""

from __future__ import annotations

import dataclasses

import httpx
import pytest
from ip.adapters.outbound.connectors.declarative_http_connector import DeclarativeHttpConnector
from ip.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DeclarativeManifest,
    HttpActionSpec,
    PaginationConfig,
    PaginationType,
    PropertyType,
)
from ip.ports.types import WriteRecordCommand


@pytest.fixture
def sample_manifest() -> DeclarativeManifest:
    prop_schema = ConnectorPropertySchema(
        app_id="mock_app",
        display_name="Mock App",
        auth_type="BEARER",
        category="CRM",
        properties=(
            ConnectorProperty(
                name="subdomain",
                label="Subdomain",
                type=PropertyType.SHORT_TEXT,
                required=True,
            ),
        ),
    )
    return DeclarativeManifest(
        app_id="mock_app",
        display_name="Mock App",
        category="CRM",
        auth_type="BEARER",
        base_url_template="https://{subdomain}.mockapp.com/api/v1",
        property_schema=prop_schema,
        check_action=HttpActionSpec(path="/ping", method="GET"),
        streams={
            "contacts": HttpActionSpec(
                path="/contacts",
                method="GET",
                pagination=PaginationConfig(
                    pagination_type=PaginationType.CURSOR,
                    cursor_param="starting_after",
                    cursor_path="next_cursor",
                    page_size=2,
                ),
                response_records_path="items",
            ),
        },
        write_actions={
            "contacts": HttpActionSpec(path="/contacts", method="POST"),
        },
    )


def test_declarative_connector_spec(sample_manifest: DeclarativeManifest) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    spec = connector.spec()
    assert spec["appId"] == "mock_app"
    assert spec["displayName"] == "Mock App"
    assert spec["authType"] == "BEARER"
    assert len(spec["properties"]) == 1
    assert spec["properties"][0]["name"] == "subdomain"


@pytest.mark.asyncio
async def test_declarative_connector_check_success(
    sample_manifest: DeclarativeManifest,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://acme.mockapp.com/api/v1/ping"
        assert request.headers.get("Authorization") == "Bearer secret-token"
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = DeclarativeHttpConnector(manifest=sample_manifest, client=client)
        result = await connector.check(
            public_config={"subdomain": "acme"},
            credentials={"access_token": "secret-token"},
        )
        assert result.success is True
        assert result.status == "SUCCEEDED"
        assert "Connected successfully" in result.message


@pytest.mark.asyncio
async def test_declarative_connector_check_failure(
    sample_manifest: DeclarativeManifest,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = DeclarativeHttpConnector(manifest=sample_manifest, client=client)
        result = await connector.check(
            public_config={"subdomain": "acme"},
            credentials={"access_token": "bad-token"},
        )
        assert result.success is False
        assert result.status == "FAILED"
        assert "HTTP 401" in result.message


@pytest.mark.asyncio
async def test_declarative_connector_discover(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    catalog = await connector.discover(
        connection_id="conn-1",
        public_config={"subdomain": "acme"},
        credentials={"access_token": "token"},
    )
    assert catalog.connection_id == "conn-1"
    assert len(catalog.streams) == 1
    assert catalog.streams[0].name == "contacts"


@pytest.mark.asyncio
async def test_declarative_connector_read_stream_with_cursor_pagination(
    sample_manifest: DeclarativeManifest,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("starting_after")
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "c1", "name": "Alice"}, {"id": "c2", "name": "Bob"}],
                    "next_cursor": "c2",
                },
            )
        elif cursor == "c2":
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "c3", "name": "Charlie"}],
                    "next_cursor": None,
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = DeclarativeHttpConnector(manifest=sample_manifest, client=client)
        records = [
            r
            async for r in connector.read_stream(
                stream_name="contacts",
                public_config={"subdomain": "acme"},
                credentials={"access_token": "token"},
                limit=10,
            )
        ]
        assert len(records) == 3
        assert records[0].record_id == "c1"
        assert records[0].data["name"] == "Alice"
        assert records[1].record_id == "c2"
        assert records[2].record_id == "c3"


@pytest.mark.asyncio
async def test_declarative_connector_write_record(
    sample_manifest: DeclarativeManifest,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == "https://acme.mockapp.com/api/v1/contacts"
        return httpx.Response(201, json={"id": "new_c99", "status": "created"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = DeclarativeHttpConnector(manifest=sample_manifest, client=client)
        result = await connector.write_record(
            stream_name="contacts",
            command=WriteRecordCommand(
                stream_name="contacts",
                operation="CREATE",
                payload={"name": "New Contact"},
            ),
            public_config={"subdomain": "acme"},
            credentials={"access_token": "token"},
        )
        assert result.success is True
        assert result.record_id == "new_c99"


@pytest.mark.asyncio
async def test_declarative_connector_write_record_rejects_unsupported_operation(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    result = await connector.write_record(
        stream_name="contacts",
        command=WriteRecordCommand(
            stream_name="contacts",
            operation="DELETE",
            payload={"id": "c1"},
        ),
        public_config={"subdomain": "acme"},
        credentials={"access_token": "token"},
    )
    assert result.success is False
    assert result.record_id == "failed"
    assert "Unsupported write operation" in (result.error_message or "")


def test_declarative_connector_extract_nested_supports_negative_indices(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    data = {"data": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
    assert connector._extract_nested(data, "data.-1.id") == "3"
    assert connector._extract_nested(data, "data.-2.id") == "2"
    assert connector._extract_nested(data, "data.-5.id") is None


def test_declarative_connector_basic_auth_header(sample_manifest: DeclarativeManifest) -> None:
    manifest = dataclasses.replace(sample_manifest, auth_type="BASIC")
    connector = DeclarativeHttpConnector(manifest=manifest)
    headers = connector._build_auth_headers({"username": "user", "password": "secret_password"})
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


def test_declarative_connector_requires_https_and_rejects_restricted_hosts(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    with pytest.raises(ValueError, match="must use HTTPS"):
        connector._interpolate_string("http://insecure.com/api", {}, {})

    with pytest.raises(ValueError, match="Restricted hostname or IP address"):
        connector._interpolate_string("https://localhost/api", {}, {})
