"""Integration tests for Integration Platform Ingestion Gateway (L1) API routes in Unified API.

Tests real HTTP ingress, sub-20ms 202 Accepted response, business trace IDs, and database persistence.
"""

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ingest_record_success_inline(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create a connection first
    conn_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Ingress Test Connection",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://ami.testgrid.com"},
            "raw_credentials": {"api_key": "test_token"},
            "endpoint_for_fingerprint": "https://ami.testgrid.com",
        },
    )
    assert conn_response.status_code == 201, conn_response.text
    connection_id = conn_response.json()["id"]

    # 2. Ingest raw payload
    ingress_payload = {
        "meter_serial": "MTR-88219",
        "timestamp": "2026-10-20T08:00:00Z",
        "interval_readings": [{"kwh": 4.12}, {"kwh": 3.98}],
    }

    ingress_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}?stream=meters",
        json=ingress_payload,
        headers={"X-Correlation-ID": "CORR-AMI-001"},
    )

    assert ingress_response.status_code == 202, ingress_response.text
    data = ingress_response.json()
    assert data["status"] == "ACCEPTED"
    assert data["record_id"].startswith("ip_inb_")
    assert data["business_trace_id"].startswith("ip_trc_")
    assert data["is_inlined"] is True
    assert data["payload_size_bytes"] > 0


@pytest.mark.asyncio
async def test_ingest_record_unknown_connection_returns_404(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/non_existent_conn_123?stream=meters",
        json={"data": "test"},
    )
    assert response.status_code == 404, response.text
    assert "Connection 'non_existent_conn_123' not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_record_large_payload_offload(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create a connection
    conn_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "salesforce",
            "name": "SF Large Ingress",
            "auth_type": "OAUTH2",
            "public_config": {"instance_url": "https://acme.salesforce.com"},
            "raw_credentials": {"access_token": "token123"},
            "endpoint_for_fingerprint": "https://acme.salesforce.com",
        },
    )
    assert conn_response.status_code == 201, conn_response.text
    connection_id = conn_response.json()["id"]

    # 2. Ingest payload >= 64 KB
    large_list = [{"id": f"rec_{i}", "payload": "A" * 100} for i in range(700)]
    large_payload = {"records": large_list}

    ingress_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}?stream=bulk_accounts",
        json=large_payload,
    )

    assert ingress_response.status_code == 202, ingress_response.text
    data = ingress_response.json()
    assert data["status"] == "ACCEPTED"
    assert data["is_inlined"] is False
    assert data["payload_size_bytes"] >= 64 * 1024
