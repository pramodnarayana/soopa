"""Unit tests for universal OLAP client adapters (ClickHouse & InMemory)."""

from __future__ import annotations

import httpx
import pytest

from database.olap import ClickHouseHttpAdapter, InMemoryOlapAdapter, OlapProvider


@pytest.mark.asyncio
async def test_in_memory_olap_adapter_insert_and_query() -> None:
    adapter = InMemoryOlapAdapter()
    assert await adapter.ping()

    # Bulk insert 5 records
    records = [
        {"tenant_id": "tenant_1", "entity_id": "E100", "metric_val": 10.5, "status": "ACTIVE"},
        {"tenant_id": "tenant_1", "entity_id": "E101", "metric_val": 20.0, "status": "ACTIVE"},
        {"tenant_id": "tenant_1", "entity_id": "E102", "metric_val": 5.0, "status": "INACTIVE"},
        {"tenant_id": "tenant_2", "entity_id": "E200", "metric_val": 15.0, "status": "ACTIVE"},
        {"tenant_id": "tenant_2", "entity_id": "E201", "metric_val": 25.0, "status": "ACTIVE"},
    ]
    inserted = await adapter.insert_batch("sample_analytics", records)
    assert inserted == 5

    # Query all tenant_1 records
    q_sql = "SELECT * FROM sample_analytics WHERE tenant_id = 'tenant_1' ORDER BY entity_id ASC LIMIT 10 OFFSET 0"
    rows = await adapter.execute_query(q_sql)
    assert len(rows) == 3
    assert rows[0]["entity_id"] == "E100"
    assert rows[1]["entity_id"] == "E101"
    assert rows[2]["entity_id"] == "E102"

    # Query parameterized
    q_param = "SELECT * FROM sample_analytics WHERE tenant_id = %(tenant_id)s ORDER BY entity_id DESC LIMIT 1 OFFSET 0"
    param_rows = await adapter.execute_query(q_param, params={"tenant_id": "tenant_2"})
    assert len(param_rows) == 1
    assert param_rows[0]["entity_id"] == "E201"

    # Count query
    count_rows = await adapter.execute_query(
        "SELECT count(*) FROM sample_analytics WHERE tenant_id = 'tenant_1'"
    )
    assert count_rows[0]["count"] == 3


@pytest.mark.asyncio
async def test_clickhouse_http_adapter_queries_and_inserts() -> None:
    # Test ClickHouseHttpAdapter with custom mock transport
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/ping" in url_str:
            return httpx.Response(200, text="Ok.\n")
        if "INSERT INTO" in url_str:
            return httpx.Response(200, text="")
        # Query response
        query_resp = {
            "meta": [{"name": "entity_id", "type": "String"}],
            "data": [{"entity_id": "MTR-100", "val": 42.0}],
            "rows": 1,
        }
        return httpx.Response(200, json=query_resp)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = ClickHouseHttpAdapter(
        endpoint_url="http://mock-clickhouse:8123",
        database="test_db",
        client=client,
    )

    # Test ping
    assert await adapter.ping()

    # Test execute_query
    res = await adapter.execute_query("SELECT * FROM test_db.readings LIMIT 1")
    assert len(res) == 1
    assert res[0]["entity_id"] == "MTR-100"

    # Test insert_batch
    batch = [{"entity_id": "MTR-101", "val": 99.0}]
    cnt = await adapter.insert_batch("readings", batch)
    assert cnt == 1

    await adapter.close()


def test_olap_provider_creates_in_memory_or_http() -> None:
    in_mem = OlapProvider.create_client(use_in_memory=True)
    assert isinstance(in_mem, InMemoryOlapAdapter)

    http_client = OlapProvider.create_client(endpoint_url="http://localhost:8123")
    assert isinstance(http_client, ClickHouseHttpAdapter)
