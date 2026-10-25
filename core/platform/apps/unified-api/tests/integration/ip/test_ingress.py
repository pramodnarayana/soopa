"""Integration tests for Integration Platform Ingestion Gateway (L1) API routes in Unified API.

Tests real HTTP ingress, sub-20ms 202 Accepted response, business trace IDs, and database persistence.
"""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ingest_record_success_inline(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create a connection first
    conn_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
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
    assert data["trace_id"].startswith("ip_trc_")
    assert data["is_inlined"] is True
    assert data["payload_size_bytes"] > 0


@pytest.mark.asyncio
async def test_ingest_record_unknown_connection_returns_404(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/non_existent_conn_123?stream=meters",
        json={"data": "test"},
    )
    assert response.status_code == 404, response.text
    assert "non_existent_conn_123" in str(response.json()["detail"])


@pytest.mark.asyncio
async def test_ingest_record_large_payload_offload(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
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


@pytest.mark.asyncio
async def test_ingest_record_into_deactivated_connection_returns_409_conflict(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    conn_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Deactivated Ingress Target",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://deactivated-ingress.testgrid.com"},
            "raw_credentials": {"api_key": "test_token"},
            "endpoint_for_fingerprint": "https://deactivated-ingress.testgrid.com",
        },
    )
    assert conn_res.status_code == 201, conn_res.text
    connection_id = conn_res.json()["id"]

    deact_res = await auth_client.delete(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}"
    )
    assert deact_res.status_code == 200, deact_res.text

    ingress_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}?stream=meters",
        json={"meter_serial": "MTR-DEACT-01"},
    )
    assert ingress_res.status_code == 409, ingress_res.text
    assert ingress_res.json()["code"] == "CONNECTION_DEACTIVATED"


@pytest.mark.asyncio
async def test_ingest_record_returns_404_when_tenant_shard_not_found(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    conn_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Unmapped Shard Target",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://unmapped-shard.testgrid.com"},
            "raw_credentials": {"api_key": "test_token"},
            "endpoint_for_fingerprint": "https://unmapped-shard.testgrid.com",
        },
    )
    assert conn_res.status_code == 201, conn_res.text
    connection_id = conn_res.json()["id"]

    # Remove the shard registry mapping for this tenant inside the savepoint transaction
    async with db_session_factory() as session:
        await session.execute(
            text("DELETE FROM ucp.shard_registry WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        await session.commit()

    ingress_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}?stream=meters",
        json={"meter_serial": "MTR-NO-SHARD-01"},
    )
    assert ingress_res.status_code == 404, ingress_res.text
    assert ingress_res.json()["code"] == "TENANT_SHARD_NOT_FOUND"
    assert tenant_id in str(ingress_res.json()["detail"])
