"""Narrow integration tests for ItronMdmConnector using local HTTP test harness (pytest_httpserver).

Zero mocks: Tests real HTTP requests, headers, status codes, and socket communication.
"""

import pytest
from ip.adapters.outbound.connectors.itron_mdm_connector import ItronMdmConnector
from ip.application.responses import WriteRecordCommand
from pytest_httpserver import HTTPServer


def test_itron_connector_spec_returns_jsonschema() -> None:
    connector = ItronMdmConnector()
    spec = connector.spec()

    assert spec["type"] == "object"
    assert "endpoint_url" in spec["required"]
    assert "api_key" in spec["required"]
    assert "properties" in spec
    assert "endpoint_url" in spec["properties"]


@pytest.mark.asyncio
async def test_itron_connector_check_connectivity_success(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
        headers={"X-API-Key": "valid_secret_key"},
    ).respond_with_json({"status": "ok", "system": "Itron Head-End"})

    connector = ItronMdmConnector()
    result = await connector.check(
        public_config={"endpoint_url": httpserver.url_for("")},
        credentials={"api_key": "valid_secret_key"},
    )

    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "successfully" in str(result.message)


@pytest.mark.asyncio
async def test_itron_connector_check_unauthorized_failure(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
    ).respond_with_json({"error": "Unauthorized"}, status=401)

    connector = ItronMdmConnector()
    result = await connector.check(
        public_config={"endpoint_url": httpserver.url_for("")},
        credentials={"api_key": "bad_key"},
    )

    assert result.success is False
    assert result.status == "FAILED"
    assert result.error_code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_itron_connector_check_missing_endpoint() -> None:
    connector = ItronMdmConnector()
    result = await connector.check(
        public_config={"endpoint_url": ""},
        credentials={"api_key": "valid_secret_key"},
    )

    assert result.success is False
    assert result.error_code == "INVALID_CONFIG"


@pytest.mark.asyncio
async def test_itron_connector_check_network_error() -> None:
    # Connect to an invalid closed local port
    connector = ItronMdmConnector(timeout_seconds=1.0)
    result = await connector.check(
        public_config={"endpoint_url": "http://127.0.0.1:59999"},
        credentials={"api_key": "secret"},
    )

    assert result.success is False
    assert result.error_code == "NETWORK_ERROR"


@pytest.mark.asyncio
async def test_itron_connector_discover_introspects_streams(httpserver: HTTPServer) -> None:
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

    connector = ItronMdmConnector()
    catalog = await connector.discover(
        connection_id="ip_conn_test123",
        public_config={"endpoint_url": httpserver.url_for("")},
        credentials={"api_key": "valid_secret_key"},
    )

    assert catalog.connection_id == "ip_conn_test123"
    assert len(catalog.streams) == 1
    stream = catalog.streams[0]
    assert stream.name == "electric_meters"
    assert len(stream.fields) == 2
    assert stream.primary_key == ["meter_id"]


@pytest.mark.asyncio
async def test_itron_connector_discover_fallback_to_canonical_streams(
    httpserver: HTTPServer,
) -> None:
    # Server returns 404 for schema introspection endpoint -> fallback to canonical AMI streams
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
    ).respond_with_data("Not found", status=404)

    connector = ItronMdmConnector()
    catalog = await connector.discover(
        connection_id="ip_conn_test123",
        public_config={"endpoint_url": httpserver.url_for("")},
        credentials={"api_key": "valid_secret_key"},
    )

    assert catalog.connection_id == "ip_conn_test123"
    stream_names = [s.name for s in catalog.streams]
    assert "meters" in stream_names
    assert "interval_reads" in stream_names
    assert "service_points" in stream_names


@pytest.mark.asyncio
async def test_itron_connector_list_and_read_records(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/streams/meters/ids",
        method="GET",
        query_string="limit=50",
    ).respond_with_json({"ids": ["mtr_101", "mtr_102"]})

    httpserver.expect_request(
        "/api/v1/streams/meters/records",
        method="GET",
        query_string="limit=100",
    ).respond_with_json(
        {
            "records": [
                {"id": "mtr_101", "serial_number": "ITR-999-01", "model": "OpenWay Riva"},
                {"id": "mtr_102", "serial_number": "ITR-999-02", "model": "Centron"},
            ]
        }
    )

    connector = ItronMdmConnector()
    ids = await connector.list_objects(
        stream_name="meters",
        public_config={"endpoint_url": httpserver.url_for("")},
        credentials={"api_key": "secret"},
        limit=50,
    )
    assert ids == ["mtr_101", "mtr_102"]

    records = [
        r
        async for r in connector.read_stream(
            stream_name="meters",
            public_config={"endpoint_url": httpserver.url_for("")},
            credentials={"api_key": "secret"},
            limit=100,
        )
    ]
    assert len(records) == 2
    assert records[0].record_id == "mtr_101"
    assert records[0].data["serial_number"] == "ITR-999-01"


@pytest.mark.asyncio
async def test_itron_connector_write_record(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/streams/meters/records",
        method="POST",
    ).respond_with_json({"id": "mtr_new_77", "destination_id": "itron_meters_77"})

    connector = ItronMdmConnector()
    cmd = WriteRecordCommand(
        stream_name="meters",
        operation="CREATE",
        payload={"serial_number": "ITR-888-01", "model": "Riva"},
    )
    result = await connector.write_record(
        stream_name="meters",
        command=cmd,
        public_config={"endpoint_url": httpserver.url_for("")},
        credentials={"api_key": "secret"},
    )

    assert result.success is True
    assert result.record_id == "mtr_new_77"
