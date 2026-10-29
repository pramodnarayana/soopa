"""Narrow integration tests for DeclarativeHttpConnector using real local HTTP socket server (pytest_httpserver).

Zero mocks, zero monkeypatch: Tests real HTTP requests, headers, pagination, status codes, and SSRF validation.
"""

from __future__ import annotations

import dataclasses

import pytest
from ip.engine.adapters.outbound.connectors.declarative_http_connector import (
    DeclarativeHttpConnector,
)
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    FailureDisposition,
    UpstreamHttpError,
)
from ip.engine.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    DeclarativeManifest,
    HttpActionSpec,
    PaginationConfig,
    PaginationType,
    PropertyType,
)
from ip.engine.ports.types import WriteRecordCommand
from pytest_httpserver import HTTPServer
from shttp import HttpClient, PassThroughPolicy, create_http_client
from shttp.resilience import HttpBackoffHandler


def _build_manifest(base_url_template: str) -> DeclarativeManifest:
    prop_schema = ConnectorPropertySchema(
        app_id="hubspot_crm",
        display_name="HubSpot CRM",
        auth_type="BEARER",
        category="CRM",
        properties=(
            ConnectorProperty(
                name="tenant_slug",
                label="Tenant Slug",
                type=PropertyType.SHORT_TEXT,
                required=True,
            ),
        ),
    )
    return DeclarativeManifest(
        app_id="hubspot_crm",
        display_name="HubSpot CRM",
        category="CRM",
        auth_type="BEARER",
        base_url_template=base_url_template,
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


@pytest.fixture
def sample_manifest() -> DeclarativeManifest:
    return _build_manifest("https://{tenant_slug}.hubapi.com/api/v1")


def test_declarative_connector_spec(sample_manifest: DeclarativeManifest) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    spec = connector.spec()
    assert spec.app_id == "hubspot_crm"
    assert spec.display_name == "HubSpot CRM"
    assert spec.auth_type == "BEARER"
    assert len(spec.properties) == 1
    assert spec.properties[0].name == "tenant_slug"


@pytest.mark.asyncio
async def test_declarative_connector_check_success(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/tenants/acme/api/v1/ping",
        method="GET",
        headers={"Authorization": "Bearer secret-token"},
    ).respond_with_json({"status": "ok"}, status=200)

    manifest = _build_manifest(f"{httpserver.url_for('')}/tenants/{{tenant_slug}}/api/v1")
    connector = DeclarativeHttpConnector(manifest=manifest, allow_private_ips=True)
    result = await connector.check(
        public_config={"tenant_slug": "acme"},
        credentials={"access_token": "secret-token"},
    )
    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "Connected successfully" in str(result.message)


@pytest.mark.asyncio
async def test_declarative_connector_check_failure(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/tenants/acme/api/v1/ping",
        method="GET",
    ).respond_with_json({"error": "Unauthorized"}, status=401)

    manifest = _build_manifest(f"{httpserver.url_for('')}/tenants/{{tenant_slug}}/api/v1")
    connector = DeclarativeHttpConnector(manifest=manifest, allow_private_ips=True)
    result = await connector.check(
        public_config={"tenant_slug": "acme"},
        credentials={"access_token": "bad-token"},
    )
    assert result.success is False
    assert result.status == "FAILED"
    assert "HTTP 401" in str(result.message)


@pytest.mark.asyncio
async def test_declarative_connector_discover(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    catalog = await connector.discover(
        connection_id="ip_conn_1",
        public_config={"tenant_slug": "acme"},
        credentials={"access_token": "token"},
    )
    assert catalog.connection_id == "ip_conn_1"
    assert len(catalog.streams) == 1
    assert catalog.streams[0].name == "contacts"


@pytest.mark.asyncio
async def test_declarative_connector_read_stream_with_cursor_pagination(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_ordered_request(
        "/tenants/acme/api/v1/contacts",
        method="GET",
    ).respond_with_json(
        {
            "items": [{"id": "c1", "name": "Alice"}, {"id": "c2", "name": "Bob"}],
            "next_cursor": "c2",
        },
        status=200,
    )
    httpserver.expect_ordered_request(
        "/tenants/acme/api/v1/contacts",
        method="GET",
        query_string="starting_after=c2&limit=2",
    ).respond_with_json(
        {
            "items": [{"id": "c3", "name": "Charlie"}],
            "next_cursor": None,
        },
        status=200,
    )

    manifest = _build_manifest(f"{httpserver.url_for('')}/tenants/{{tenant_slug}}/api/v1")
    connector = DeclarativeHttpConnector(manifest=manifest, allow_private_ips=True)
    records = [
        r
        async for r in connector.read_stream(
            stream_name="contacts",
            public_config={"tenant_slug": "acme"},
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
async def test_declarative_connector_write_record(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/tenants/acme/api/v1/contacts",
        method="POST",
    ).respond_with_json({"id": "new_c99", "status": "created"}, status=201)

    manifest = _build_manifest(f"{httpserver.url_for('')}/tenants/{{tenant_slug}}/api/v1")
    connector = DeclarativeHttpConnector(manifest=manifest, allow_private_ips=True)
    result = await connector.write_record(
        stream_name="contacts",
        command=WriteRecordCommand(
            stream_name="contacts",
            operation="CREATE",
            payload={"name": "New Contact"},
        ),
        public_config={"tenant_slug": "acme"},
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
        public_config={"tenant_slug": "acme"},
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
    auth = connector._build_auth_payload({"username": "user", "password": "secret_password"})
    assert "Authorization" in auth.headers
    assert auth.headers["Authorization"].startswith("Basic ")
    assert "Authorization" in auth.sensitive_header_names
    assert auth.params == {}


def test_declarative_connector_query_param_auth(sample_manifest: DeclarativeManifest) -> None:
    manifest = dataclasses.replace(sample_manifest, auth_type="API_KEY")
    connector = DeclarativeHttpConnector(manifest=manifest)
    auth = connector._build_auth_payload(
        {"api_key": "secret_key_123", "param_name": "apiKey", "placement": "query"}
    )
    assert auth.headers == {}
    assert "apiKey" in auth.params
    assert auth.params["apiKey"] == "secret_key_123"
    assert tuple(auth.sensitive_header_names) == ()


def test_declarative_connector_requires_https_and_rejects_restricted_hosts(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    http_res = connector._interpolate_string("http://insecure.com/api", {}, {})
    assert http_res.is_err is True
    assert isinstance(http_res.error, EndpointSecurityViolationError)
    assert "must use HTTPS" in http_res.error.message

    local_res = connector._interpolate_string("https://localhost/api", {}, {})
    assert local_res.is_err is True
    assert isinstance(local_res.error, EndpointSecurityViolationError)
    assert "Restricted hostname or IP address" in local_res.error.message


@pytest.mark.asyncio
async def test_declarative_connector_check_handles_invalid_configuration(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    result = await connector.check(
        public_config={"tenant_slug": "invalid/subdomain;injection"},
        credentials={},
    )
    assert result.success is False
    assert result.status == "FAILED"
    assert result.error_code == "INVALID_CONFIGURATION"


def test_declarative_connector_rejects_cursor_url_with_mismatched_origin(
    sample_manifest: DeclarativeManifest,
) -> None:
    connector = DeclarativeHttpConnector(manifest=sample_manifest)
    action = sample_manifest.streams["contacts"]

    res = connector._prepare_page_url_and_params(
        action=action,
        base_url="https://api.example.com",
        current_cursor="https://malicious.com/api/contacts?cursor=123",
        current_page=1,
        current_offset=0,
        limit=10,
        records_emitted=0,
    )
    assert res.is_err is True
    assert isinstance(res.error, EndpointSecurityViolationError)
    assert "Pagination cursor URL origin" in res.error.message


@pytest.mark.asyncio
async def test_declarative_connector_fetch_page_handles_http_error(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/contacts",
        method="GET",
    ).respond_with_data("Internal Server Error", status=500)

    http_client = HttpClient(
        client=create_http_client(timeout=1.0),
        backoff_handler=HttpBackoffHandler(max_retries=0),
        allow_private_ips=True,
        response_policy=PassThroughPolicy(),
    )
    manifest = _build_manifest(httpserver.url_for(""))
    connector = DeclarativeHttpConnector(
        manifest=manifest, http_client=http_client, allow_private_ips=True
    )
    action = manifest.streams["contacts"]

    page_res = await connector._fetch_records_page(
        action=action,
        credentials={"api_key": "test_key"},
        req_url=httpserver.url_for("/contacts"),
        params={},
    )
    assert page_res.is_err is True
    assert isinstance(page_res.error, UpstreamHttpError)
    assert page_res.error.status_code == 500
    assert page_res.error.disposition == FailureDisposition.RETRY


@pytest.mark.asyncio
async def test_declarative_connector_write_record_injects_idempotency_key_and_extracts_retry_after(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/contacts",
        method="POST",
        headers={"Idempotency-Key": "idem-decl-429"},
    ).respond_with_json(
        {"error": "rate_limit_exceeded"},
        status=429,
        headers={"Retry-After": "30"},
    )

    http_client = HttpClient(
        client=create_http_client(timeout=1.0),
        backoff_handler=HttpBackoffHandler(max_retries=0),
        allow_private_ips=True,
        response_policy=PassThroughPolicy(),
    )
    manifest = _build_manifest(httpserver.url_for(""))
    connector = DeclarativeHttpConnector(
        manifest=manifest,
        http_client=http_client,
        allow_private_ips=True,
    )

    result = await connector.write_record(
        stream_name="contacts",
        command=WriteRecordCommand(
            stream_name="contacts",
            operation="CREATE",
            payload={"name": "Throttled Contact"},
            idempotency_key="idem-decl-429",
        ),
        public_config={"tenant_slug": "acme"},
        credentials={"api_key": "test_key"},
    )
    assert result.success is False
    assert result.response_status_code == 429
    assert result.retry_after_seconds == 30.0
    assert result.request_headers is not None
    assert result.request_headers.get("Idempotency-Key") == "idem-decl-429"


@pytest.mark.asyncio
async def test_declarative_connector_auth_params_remain_authoritative_on_conflict(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/tenants/acme/api/v1/ping",
        method="GET",
        query_string="apiKey=auth_authoritative_key",
    ).respond_with_json({"status": "ok"}, status=200)

    base_manifest = _build_manifest(f"{httpserver.url_for('')}/tenants/{{tenant_slug}}/api/v1")
    manifest = dataclasses.replace(
        base_manifest,
        auth_type="API_KEY",
        check_action=HttpActionSpec(
            path="/ping",
            method="GET",
            query_params={"apiKey": "conflicting_action_key"},
        ),
    )
    connector = DeclarativeHttpConnector(manifest=manifest, allow_private_ips=True)
    result = await connector.check(
        public_config={"tenant_slug": "acme"},
        credentials={
            "api_key": "auth_authoritative_key",
            "param_name": "apiKey",
            "placement": "query",
        },
    )
    assert result.success is True
    assert result.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_declarative_connector_fetch_page_auth_params_override_cursor_query(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/tenants/acme/api/v1/contacts",
        method="GET",
        query_string="cursor=abc&apiKey=auth_authoritative_key",
    ).respond_with_json({"items": [{"id": "1"}], "next_cursor": None}, status=200)

    base_manifest = _build_manifest(f"{httpserver.url_for('')}/tenants/{{tenant_slug}}/api/v1")
    manifest = dataclasses.replace(base_manifest, auth_type="API_KEY")
    connector = DeclarativeHttpConnector(manifest=manifest, allow_private_ips=True)
    action = manifest.streams["contacts"]
    res = await connector._fetch_records_page(
        action=action,
        credentials={
            "api_key": "auth_authoritative_key",
            "param_name": "apiKey",
            "placement": "query",
        },
        req_url=f"{httpserver.url_for('')}/tenants/acme/api/v1/contacts?cursor=abc&apiKey=stale_cursor_key",
        params={},
    )
    assert res.is_ok is True
    records, _next_cur, _has_more = res.unwrap()
    assert len(records) == 1
