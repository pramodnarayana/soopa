"""Integration tests for Integration Platform Connections API routes in Unified API.

Tests real HTTP requests, perimeter authentication, tenant isolation, and live database persistence.
"""

from typing import Any

import httpx
import pytest
from pytest_httpserver import HTTPServer

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_check_connection_credentials(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
        headers={"X-API-Key": "test_secret_key"},
    ).respond_with_json({"status": "ok", "system": "Itron Head-End"})

    tenant_id = seeded_api_token["tenant_id"]
    response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/check",
        json={
            "app_id": "itron_mdm",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": httpserver.url_for("")},
            "raw_credentials": {"api_key": "test_secret_key"},
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_create_and_get_connection_lifecycle(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create Connection
    create_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Utility Main Grid Itron",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://ami.utility.com"},
            "raw_credentials": {"api_key": "super_secret_token_123"},
            "endpoint_for_fingerprint": "https://ami.utility.com",
        },
    )
    assert create_response.status_code == 201, create_response.text
    created_conn = create_response.json()
    connection_id = created_conn["id"]
    assert connection_id.startswith("ip_conn_")
    assert created_conn["tenant_id"] == tenant_id
    assert created_conn["name"] == "Utility Main Grid Itron"
    assert created_conn["status"] == "PENDING_AUTH"

    # Credentials must NEVER be returned in response DTO
    assert "raw_credentials" not in created_conn
    assert "encrypted_credentials" not in created_conn

    # 2. Get Connection by ID
    get_response = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}"
    )
    assert get_response.status_code == 200, get_response.text
    fetched_conn = get_response.json()
    assert fetched_conn["id"] == connection_id
    assert fetched_conn["name"] == "Utility Main Grid Itron"

    # 3. List Connections
    list_response = await auth_client.get(f"/api/v1/tenants/{tenant_id}/ip/connections")
    assert list_response.status_code == 200, list_response.text
    connections = list_response.json()
    assert any(c["id"] == connection_id for c in connections)


@pytest.mark.asyncio
async def test_discover_connection_catalog(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_data("Not found", status=404)

    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create Connection pointing to httpserver
    create_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Itron Introspect Connection",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": httpserver.url_for("")},
            "raw_credentials": {"api_key": "valid_token"},
            "endpoint_for_fingerprint": httpserver.url_for(""),
        },
    )
    assert create_response.status_code == 201, create_response.text
    connection_id = create_response.json()["id"]

    # 2. Trigger Discover Catalog
    discover_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/discover"
    )
    assert discover_response.status_code == 200, discover_response.text
    catalog_data = discover_response.json()
    assert catalog_data["connection_id"] == connection_id
    assert catalog_data["catalog_version"] == 1
    assert len(catalog_data["streams"]) == 3
    stream_names = [s["name"] for s in catalog_data["streams"]]
    assert "meters" in stream_names


@pytest.mark.asyncio
async def test_deactivate_and_relink_connection(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    create_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Itron Deactivation Target",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://ami.gridpower.com"},
            "raw_credentials": {"api_key": "valid_token"},
            "endpoint_for_fingerprint": "https://ami.gridpower.com",
        },
    )
    assert create_response.status_code == 201, create_response.text
    connection_id = create_response.json()["id"]

    # 1. Deactivate
    deact_response = await auth_client.delete(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}"
    )
    assert deact_response.status_code == 200, deact_response.text
    deact_data = deact_response.json()
    assert deact_data["status"] == "DEACTIVATED"
    assert deact_data["deactivated_at"] is not None

    # 2. Relink
    relink_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/relink",
        json={
            "new_name": "Itron Re-activated",
            "updated_raw_credentials": {"api_key": "new_fresh_key"},
        },
    )
    assert relink_response.status_code == 200, relink_response.text
    relinked_data = relink_response.json()
    assert relinked_data["status"] == "ACTIVE"
    assert relinked_data["name"] == "Itron Re-activated"
