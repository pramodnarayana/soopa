"""Narrow integration tests for GenericHttpConnector using local HTTP test harness (pytest_httpserver).

Zero mocks: Tests real HTTP requests, headers, status codes, socket communication, and declarative stream configs.
"""

from __future__ import annotations

import httpx
import pytest
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.connectors.generic_http_connector import GenericHttpConnector
from ip.engine.ports.outbound.connector_port import WriteRecordCommand
from pytest_httpserver import HTTPServer
from seedwork.domain.types import JsonDict
from shttp import HttpClient, PassThroughPolicy, create_http_client
from shttp.resilience import HttpBackoffHandler


def test_generic_http_connector_spec() -> None:
    connector = GenericHttpConnector(app_id="http", auth_resolver=AuthStrategyResolver())
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
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
    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver())
    result = await connector.check(
        public_config={"base_url": ""},
        credentials={"api_key": "valid_secret_key"},
    )

    assert result.success is False
    assert result.error_code == "INVALID_CONFIG"


@pytest.mark.asyncio
async def test_generic_http_connector_rejects_private_ips_by_default() -> None:
    connector = GenericHttpConnector(
        auth_resolver=AuthStrategyResolver()
    )  # default allow_private_ips=False
    result = await connector.check(
        public_config={"base_url": "http://127.0.0.1:8080"},
        credentials={"api_key": "secret"},
    )
    assert result.success is False
    assert result.error_code == "NETWORK_ERROR"
    assert "SSRF" in str(result.message) or "restricted" in str(result.message).lower()


@pytest.mark.asyncio
async def test_generic_http_connector_check_network_error() -> None:
    connector = GenericHttpConnector(
        auth_resolver=AuthStrategyResolver(),
        timeout_seconds=1.0,
        allow_private_ips=True,
    )
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
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

    public_config: JsonDict = {
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
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
    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), http_client=fast_client)
    public_config: JsonDict = {
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
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

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
    public_config: JsonDict = {
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


@pytest.mark.asyncio
async def test_generic_http_connector_write_record_upsert_and_rate_limit_extraction(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/streams/meters/records/mtr_99",
        method="PUT",
        headers={"Idempotency-Key": "idem-mtr-99", "X-Custom": "grid"},
    ).respond_with_json({"id": "mtr_99", "updated": True}, status=200)

    fast_client = HttpClient(
        client=create_http_client(timeout=1.0),
        backoff_handler=HttpBackoffHandler(max_retries=0),
        allow_private_ips=True,
        response_policy=PassThroughPolicy(),
    )
    connector = GenericHttpConnector(
        auth_resolver=AuthStrategyResolver(),
        http_client=fast_client,
        allow_private_ips=True,
    )
    public_config: JsonDict = {
        "base_url": httpserver.url_for(""),
        "auth_type": "API_KEY",
        "streams": [
            {
                "name": "meters",
                "path": "/api/v1/streams/meters/records",
            }
        ],
    }

    upsert_res = await connector.write_record(
        stream_name="meters",
        command=WriteRecordCommand(
            stream_name="meters",
            operation="UPSERT",
            payload={"id": "mtr_99", "serial_number": "ITR-99"},
            record_id="mtr_99",
            idempotency_key="idem-mtr-99",
            headers={"X-Custom": "grid"},
        ),
        public_config=public_config,
        credentials={"api_key": "secret"},
    )
    assert upsert_res.success is True
    assert upsert_res.record_id == "mtr_99"
    assert upsert_res.http_method == "PUT"
    assert upsert_res.target_url.endswith("/api/v1/streams/meters/records/mtr_99")

    # Rate limit 429 with Retry-After header
    httpserver.expect_request(
        "/api/v1/streams/meters/records",
        method="POST",
    ).respond_with_json(
        {"error": "slow_down"},
        status=429,
        headers={"Retry-After": "15"},
    )
    throttled_res = await connector.write_record(
        stream_name="meters",
        command=WriteRecordCommand(
            stream_name="meters",
            operation="CREATE",
            payload={"serial_number": "ITR-100"},
        ),
        public_config=public_config,
        credentials={"api_key": "secret"},
    )
    assert throttled_res.success is False
    assert throttled_res.response_status_code == 429
    assert throttled_res.retry_after_seconds == 15.0


@pytest.mark.asyncio
async def test_generic_http_connector_merges_public_config_auth_parameters_into_authenticator(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/custom-stream",
        method="GET",
        headers={"X-Custom-Header": "my_api_key"},
    ).respond_with_json({"data": [{"id": "rec_01", "name": "Device 1"}]})

    connector = GenericHttpConnector(auth_resolver=AuthStrategyResolver(), allow_private_ips=True)
    public_config = {
        "base_url": httpserver.url_for(""),
        "auth_type": "API_KEY",
        "param_name": "X-Custom-Header",
        "placement": "HEADER",
        "streams": [
            {
                "name": "custom-stream",
                "path": "/api/v1/custom-stream",
                "record_path": ["data"],
            }
        ],
    }

    records = [
        rec
        async for rec in connector.read_stream(
            stream_name="custom-stream",
            public_config=public_config,
            credentials={"token": "my_api_key"},
        )
    ]

    assert len(records) == 1
    assert records[0].record_id == "rec_01"
    assert records[0].data["name"] == "Device 1"


@pytest.mark.asyncio
async def test_generic_http_connector_applies_per_connection_timeout_without_mutating_connector() -> (
    None
):
    observed_timeouts: list[dict[str, float | None]] = []

    def _transport_handler(req: httpx.Request) -> httpx.Response:
        raw_timeout = req.extensions.get("timeout")
        if isinstance(raw_timeout, dict):
            observed_timeouts.append(raw_timeout)
        return httpx.Response(200, json={"data": [{"id": "rec_01"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_transport_handler)) as raw_client:
        connector = GenericHttpConnector(
            auth_resolver=AuthStrategyResolver(),
            client=raw_client,
        )

        # 1. Omitted timeout_seconds honors the advertised 30.0s default
        default_res = await connector.check(
            public_config={
                "base_url": "http://127.0.0.1",
                "auth_type": "NO_AUTH",
            },
            credentials={},
        )
        assert default_res.success is True
        assert observed_timeouts[-1] == {"connect": 30.0, "read": 30.0, "write": 30.0, "pool": 30.0}

        # 2. Per-connection timeout_seconds overrides per request without mutating shared connector
        slow_res = await connector.check(
            public_config={
                "base_url": "http://127.0.0.1",
                "auth_type": "NO_AUTH",
                "timeout_seconds": 45,
            },
            credentials={},
        )
        assert slow_res.success is True
        assert observed_timeouts[-1] == {"connect": 45.0, "read": 45.0, "write": 45.0, "pool": 45.0}

        # 3. Subsequent call without timeout_seconds still uses 30.0s default across read/write
        write_res = await connector.write_record(
            stream_name="items",
            command=WriteRecordCommand(
                stream_name="items",
                operation="CREATE",
                payload={"name": "Widget"},
            ),
            public_config={"base_url": "http://127.0.0.1", "auth_type": "NO_AUTH"},
            credentials={},
        )
        assert write_res.success is True
        assert observed_timeouts[-1] == {"connect": 30.0, "read": 30.0, "write": 30.0, "pool": 30.0}

        # 4. Invalid timeout_seconds values are rejected cleanly
        for bad_timeout in (0, -5, True, "nan", "abc"):
            invalid_res = await connector.check(
                public_config={
                    "base_url": "http://127.0.0.1",
                    "auth_type": "NO_AUTH",
                    "timeout_seconds": bad_timeout,
                },
                credentials={},
            )
            assert invalid_res.success is False
            assert invalid_res.error_code == "INVALID_CONFIG"
