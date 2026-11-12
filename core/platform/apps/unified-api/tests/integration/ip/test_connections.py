"""Integration tests for Integration Platform Connections API routes in Unified API.

Tests real HTTP requests, perimeter authentication, tenant isolation, and live database persistence.
"""

import httpx
import pytest
from pytest_httpserver import HTTPServer

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_check_connection_credentials(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
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
            "app_id": "http",
            "auth_type": "API_KEY",
            "public_config": {
                "endpoint_url": httpserver.url_for(""),
                "check_path": "/api/v1/health",
            },
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
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create Connection
    create_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
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
    seeded_api_token: dict[str, str],
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_json(
        {
            "streams": [
                {
                    "name": "meters",
                    "fields": [{"name": "id", "data_type": "string", "nullable": False}],
                    "primary_key": ["id"],
                    "supported_sync_modes": ["FULL_REFRESH", "INCREMENTAL"],
                },
                {
                    "name": "interval_reads",
                    "fields": [{"name": "meter_id", "data_type": "string", "nullable": False}],
                    "primary_key": ["meter_id"],
                    "supported_sync_modes": ["FULL_REFRESH", "INCREMENTAL"],
                },
                {
                    "name": "service_points",
                    "fields": [{"name": "id", "data_type": "string", "nullable": False}],
                    "primary_key": ["id"],
                    "supported_sync_modes": ["FULL_REFRESH"],
                },
            ]
        },
        status=200,
    )

    tenant_id = seeded_api_token["tenant_id"]

    # 1. Create Connection pointing to httpserver
    create_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
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
    assert "catalog_version" not in catalog_data
    assert len(catalog_data["streams"]) == 3
    stream_names = [s["name"] for s in catalog_data["streams"]]
    assert "meters" in stream_names


@pytest.mark.asyncio
async def test_deactivate_and_relink_connection(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    create_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
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


@pytest.mark.asyncio
async def test_create_duplicate_active_connection_returns_409_conflict(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    payload = {
        "app_id": "http",
        "name": "Primary Grid Connection",
        "auth_type": "API_KEY",
        "public_config": {"endpoint_url": "https://duplicate-test.gridpower.com"},
        "raw_credentials": {"api_key": "token_1"},
        "endpoint_for_fingerprint": "https://duplicate-test.gridpower.com",
    }

    first_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json=payload,
    )
    assert first_res.status_code == 201, first_res.text

    second_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={**payload, "name": "Duplicate Grid Connection"},
    )
    assert second_res.status_code == 409, second_res.text
    assert second_res.json()["code"] == "DUPLICATE_FINGERPRINT"


@pytest.mark.asyncio
async def test_relink_non_deactivated_connection_returns_409_conflict(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    create_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
            "name": "Active Non-Deactivated Connection",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://active-relink.gridpower.com"},
            "raw_credentials": {"api_key": "token_1"},
            "endpoint_for_fingerprint": "https://active-relink.gridpower.com",
        },
    )
    assert create_res.status_code == 201, create_res.text
    connection_id = create_res.json()["id"]

    relink_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/relink",
        json={
            "new_name": "Should Fail Relink",
            "updated_raw_credentials": {"api_key": "token_2"},
        },
    )
    assert relink_res.status_code == 409, relink_res.text
    assert relink_res.json()["code"] == "INVALID_CONNECTION_STATE"


@pytest.mark.asyncio
async def test_create_connection_invalid_auth_type_returns_422(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": "Bad Auth Type",
            "auth_type": "UNSUPPORTED_KERBEROS_V9",
            "public_config": {"endpoint_url": "https://kerberos.gridpower.com"},
            "raw_credentials": {},
            "endpoint_for_fingerprint": "https://kerberos.gridpower.com",
        },
    )
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert isinstance(detail, list)
    assert any("auth_type" in str(err.get("loc", [])) for err in detail)


@pytest.mark.asyncio
async def test_update_connection_metadata_returns_200_ok(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    create_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
            "name": "Initial Connection Name",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://update-test.gridpower.com"},
            "raw_credentials": {"api_key": "token_init"},
            "endpoint_for_fingerprint": "https://update-test.gridpower.com",
        },
    )
    assert create_res.status_code == 201, create_res.text
    connection_id = create_res.json()["id"]

    update_res = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}",
        json={
            "new_name": "Updated Connection Name",
            "updated_public_config": {"endpoint_url": "https://update-test.gridpower.com/v2"},
            "updated_raw_credentials": {"api_key": "token_updated"},
        },
    )
    assert update_res.status_code == 200, update_res.text
    updated = update_res.json()
    assert updated["id"] == connection_id
    assert updated["name"] == "Updated Connection Name"
    assert updated["public_config"] == {"endpoint_url": "https://update-test.gridpower.com/v2"}
    assert "raw_credentials" not in updated


@pytest.mark.asyncio
async def test_update_deactivated_connection_returns_409_conflict(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    create_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
            "name": "Connection To Deactivate",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://deact-test.gridpower.com"},
            "raw_credentials": {"api_key": "token_1"},
            "endpoint_for_fingerprint": "https://deact-test.gridpower.com",
        },
    )
    assert create_res.status_code == 201, create_res.text
    connection_id = create_res.json()["id"]

    deact_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/deactivate",
    )
    assert deact_res.status_code == 200, deact_res.text
    assert deact_res.json()["status"] == "DEACTIVATED"

    update_res = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}",
        json={"new_name": "Should Conflict"},
    )
    assert update_res.status_code == 409, update_res.text
    assert update_res.json()["code"] == "INVALID_CONNECTION_STATE"


@pytest.mark.asyncio
async def test_update_nonexistent_connection_returns_404_not_found(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    res = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/ip/connections/ip_conn_nonexistent_12345",
        json={"new_name": "Ghost Connection"},
    )
    assert res.status_code == 404, res.text
    assert res.json()["code"] == "CONNECTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_connection_entities_subscription_lifecycle(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    create_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "http",
            "name": "Entities Control Plane Connection",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": "https://entities.gridpower.com"},
            "raw_credentials": {"api_key": "token_entities"},
            "endpoint_for_fingerprint": "https://entities.gridpower.com",
        },
    )
    assert create_res.status_code == 201, create_res.text
    connection_id = create_res.json()["id"]

    # 1. Subscribe an entity on the connection
    add_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/entities",
        json={
            "stream_name": "orders",
            "sync_mode": "INCREMENTAL",
            "schedule": "1h",
            "sync_from": "all",
            "primary_key": ["order_id"],
            "fields": [
                {"name": "order_id", "data_type": "string", "nullable": False},
                {"name": "total_cents", "data_type": "integer", "nullable": False},
            ],
            "cursor_field": "updated_at",
        },
    )
    assert add_res.status_code == 201, add_res.text
    added = add_res.json()
    assert added["entity_id"].startswith("ip_cent_")
    assert added["stream_name"] == "orders"
    assert added["schedule"] == "1h"
    assert added["sync_from"] == "all"
    assert added["primary_key"] == ["order_id"]
    assert len(added["fields"]) == 2
    assert added["records_synced_count"] == 0
    assert added["last_synced_at"] is None

    # 2. Subsequent GET returns persisted subscribed entity across navigation/reloads
    list_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/entities"
    )
    assert list_res.status_code == 200, list_res.text
    listed = list_res.json()
    assert len(listed) == 1
    assert listed[0]["stream_name"] == "orders"
    assert len(listed[0]["fields"]) == 2

    # 3. Update sync schedule and custom start date
    patch_res = await auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/entities/orders",
        json={
            "schedule": "15m",
            "sync_from": "custom",
            "sync_from_at": "2026-01-15T00:00:00Z",
        },
    )
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()
    assert patched["schedule"] == "15m"
    assert patched["sync_from"] == "custom"
    assert patched["sync_from_at"] is not None

    # 4. Unsubscribe / remove entity
    del_res = await auth_client.delete(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/entities/orders"
    )
    assert del_res.status_code == 204, del_res.text

    after_del_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/entities"
    )
    assert after_del_res.status_code == 200, after_del_res.text
    assert after_del_res.json() == []
