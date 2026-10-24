"""Narrow integration tests for GenericHttpConnector using local HTTP test harness (pytest_httpserver).

Zero mocks: Tests real HTTP requests, headers, status codes, socket communication, and declarative stream configs.
"""

from __future__ import annotations

import pytest
from ip.engine.adapters.outbound.connectors.generic_http_connector import GenericHttpConnector
from ip.engine.application.responses import WriteRecordCommand
from pytest_httpserver import HTTPServer
from shttp import HttpClient, PassThroughPolicy, create_http_client
from shttp.resilience import HttpBackoffHandler


def test_generic_http_connector_spec() -> None:
    connector = GenericHttpConnector(app_id="http")
    spec = connector.spec()

    assert spec.app_id == "http"
    assert spec.display_name == "HTTP / REST API"
    assert spec.category == "API"
    prop_names = [p.name for p in spec.properties]
    assert "base_url" in prop_names
    assert "auth_type" in prop_names


@pytest.mark.asyncio
async def test_generic_http_connector_check_connectivity_success(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
        headers={"X-API-Key": "valid_secret_key"},
    ).respond_with_json({"status": "ok", "system": "Upstream API"})

    connector = GenericHttpConnector(allow_private_ips=True)
    result = await connector.check(
        public_config={
            "base_url": httpserver.url_for(""),
            "auth_type": "API_KEY",
            "check_path": "/api/v1/health",
        },
        credentials={"api_key": "valid_secret_key"},
    )

    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "successfully" in str(result.message)


@pytest.mark.asyncio
async def test_generic_http_connector_check_unauthorized_failure(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
    ).respond_with_json({"error": "Unauthorized"}, status=401)

    connector = GenericHttpConnector(allow_private_ips=True)
    result = await connector.check(
        public_config={
            "base_url": httpserver.url_for(""),
            "auth_type": "API_KEY",
            "check_path": "/api/v1/health",
        },
        credentials={"api_key": "bad_key"},
    )

    assert result.success is False
    assert result.status == "FAILED"
    assert result.error_code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_generic_http_connector_check_missing_endpoint() -> None:
    connector = GenericHttpConnector()
    result = await connector.check(
        public_config={"base_url": ""},
        credentials={"api_key": "valid_secret_key"},
    )

    assert result.success is False
    assert result.error_code == "INVALID_CONFIG"


@pytest.mark.asyncio
async def test_generic_http_connector_rejects_private_ips_by_default() -> None:
    connector = GenericHttpConnector()  # default allow_private_ips=False
    result = await connector.check(
        public_config={"base_url": "http://127.0.0.1:8080"},
        credentials={"api_key": "secret"},
    )
    assert result.success is False
    assert result.error_code == "NETWORK_ERROR"
    assert "SSRF" in str(result.message) or "restricted" in str(result.message).lower()


@pytest.mark.asyncio
async def test_generic_http_connector_check_network_error() -> None:
    connector = GenericHttpConnector(timeout_seconds=1.0, allow_private_ips=True)
    result = await connector.check(
        public_config={"base_url": "http://127.0.0.1:59999"},
        credentials={"api_key": "secret"},
    )

    assert result.success is False
    assert result.error_code == "NETWORK_ERROR"


@pytest.mark.asyncio
async def test_generic_http_connector_discover_introspects_streams(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
        headers={"X-API-Key": "valid_secret_key"},
    ).respond_with_json(
        {
            "streams": [
                {
                    "name": "electric_meters",
                    "fields": [
                        {"name": "meter_id", "data_type": "string", "nullable": False},
                        {"name": "firmware", "data_type": "string"},
                    ],
                    "primary_key": ["meter_id"],
                    "supported_sync_modes": ["FULL_REFRESH", "INCREMENTAL"],
                }
            ]
        }
    )

    connector = GenericHttpConnector(allow_private_ips=True)
    catalog = await connector.discover(
        connection_id="ip_conn_test123",
        public_config={
            "base_url": httpserver.url_for(""),
            "auth_type": "API_KEY",
        },
        credentials={"api_key": "valid_secret_key"},
    )

    assert catalog.connection_id == "ip_conn_test123"
    assert len(catalog.streams) == 1
    stream = catalog.streams[0]
    assert stream.name == "electric_meters"
    assert len(stream.fields) == 2
    assert stream.primary_key == ["meter_id"]


@pytest.mark.asyncio
async def test_generic_http_connector_discover_fallback_to_records_stream(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
    ).respond_with_data("Not found", status=404)

    connector = GenericHttpConnector(allow_private_ips=True)
    catalog = await connector.discover(
        connection_id="ip_conn_test123",
        public_config={
            "base_url": httpserver.url_for(""),
            "auth_type": "API_KEY",
        },
        credentials={"api_key": "valid_secret_key"},
    )

    assert catalog.connection_id == "ip_conn_test123"
    stream_names = [s.name for s in catalog.streams]
    assert "records" in stream_names


@pytest.mark.asyncio
async def test_generic_http_connector_list_and_read_records(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/streams/meters/records",
        method="GET",
    ).respond_with_json(
        {
            "records": [
                {"id": "mtr_101", "serial_number": "ITR-999-01", "model": "OpenWay Riva"},
                {"id": "mtr_102", "serial_number": "ITR-999-02", "model": "Centron"},
            ]
        }
    )

    public_config = {
        "base_url": httpserver.url_for(""),
        "auth_type": "API_KEY",
        "streams": [
            {
                "name": "meters",
                "path": "/api/v1/streams/meters/records",
                "record_path": ["records"],
                "primary_key": ["id"],
            }
        ],
    }

    connector = GenericHttpConnector(allow_private_ips=True)
    records = [
        r
        async for r in connector.read_stream(
            stream_name="meters",
            public_config=public_config,
            credentials={"api_key": "secret"},
            limit=100,
        )
    ]
    assert len(records) == 2
    assert records[0].record_id == "mtr_101"
    assert records[0].data["serial_number"] == "ITR-999-01"

    ids = await connector.list_objects(
        stream_name="meters",
        public_config=public_config,
        credentials={"api_key": "secret"},
        limit=50,
    )
    assert ids == ["mtr_101", "mtr_102"]


@pytest.mark.asyncio
async def test_generic_http_connector_read_records_handle_error_gracefully(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/streams/meters/records",
        method="GET",
    ).respond_with_data("Server Error", status=500)

    fast_client = HttpClient(
        client=create_http_client(timeout=1.0),
        backoff_handler=HttpBackoffHandler(max_retries=0),
        allow_private_ips=True,
        response_policy=PassThroughPolicy(),
    )
    connector = GenericHttpConnector(http_client=fast_client)
    public_config = {
        "base_url": httpserver.url_for(""),
        "auth_type": "API_KEY",
        "streams": [
            {
                "name": "meters",
                "path": "/api/v1/streams/meters/records",
            }
        ],
    }
    ids = await connector.list_objects(
        stream_name="meters",
        public_config=public_config,
        credentials={"api_key": "secret"},
    )
    assert ids == []

    records = [
        r
        async for r in connector.read_stream(
            stream_name="meters",
            public_config=public_config,
            credentials={"api_key": "secret"},
        )
    ]
    assert records == []


@pytest.mark.asyncio
async def test_generic_http_connector_discover_returns_failure_result_on_auth_error(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
    ).respond_with_data("Unauthorized", status=401)

    connector = GenericHttpConnector(allow_private_ips=True)
    catalog = await connector.discover(
        connection_id="ip_conn_test123",
        public_config={
            "base_url": httpserver.url_for(""),
            "auth_type": "API_KEY",
        },
        credentials={"api_key": "bad_key"},
    )
    assert catalog.success is False
    assert catalog.error_code == "UNAUTHORIZED"
    assert "Authentication failed" in (catalog.error_message or "")


@pytest.mark.asyncio
async def test_generic_http_connector_write_record(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/streams/meters/records",
        method="POST",
    ).respond_with_json({"id": "mtr_new_77", "destination_id": "api_meters_77"})

    connector = GenericHttpConnector(allow_private_ips=True)
    public_config = {
        "base_url": httpserver.url_for(""),
        "auth_type": "API_KEY",
        "streams": [
            {
                "name": "meters",
                "path": "/api/v1/streams/meters/records",
            }
        ],
    }
    cmd = WriteRecordCommand(
        stream_name="meters",
        operation="CREATE",
        payload={"serial_number": "ITR-888-01", "model": "Riva"},
    )
    result = await connector.write_record(
        stream_name="meters",
        command=cmd,
        public_config=public_config,
        credentials={"api_key": "secret"},
    )

    assert result.success is True
    assert result.record_id == "mtr_new_77"
