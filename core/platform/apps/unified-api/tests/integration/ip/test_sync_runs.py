"""Narrow PostgreSQL integration tests for IP Control Plane Sync Runs & Stream State API routes."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


async def _create_sync_connection(
    auth_client: httpx.AsyncClient,
    tenant_id: str,
    name_suffix: str,
) -> str:
    res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": f"Sync Test {name_suffix}",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": f"https://sync-{name_suffix.lower()}.testgrid.com"},
            "raw_credentials": {"api_key": "test_token"},
            "endpoint_for_fingerprint": f"https://sync-{name_suffix.lower()}.testgrid.com",
        },
    )
    assert res.status_code == 201, res.text
    conn_id: str = res.json()["id"]
    return conn_id


@pytest.mark.asyncio
async def test_sync_runs_trigger_conflict_list_get_and_stream_state_reset(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    connection_id = await _create_sync_connection(auth_client, tenant_id, "pull-1")

    # 1. Trigger a pull sync run -> 202 Accepted
    trigger_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/sync-runs",
        json={
            "stream_name": "meters",
            "forced_kind": "INITIAL",
            "correlation_id": "corr-sync-101",
        },
    )
    assert trigger_res.status_code == 202, trigger_res.text
    sync_run = trigger_res.json()
    run_id = sync_run["run_id"]
    assert run_id.startswith("ip_sync_")
    assert sync_run["status"] == "PENDING"
    assert sync_run["kind"] == "INITIAL"
    assert sync_run["stream_name"] == "meters"
    assert sync_run["trace_id"] is not None

    # 2. Triggering a second concurrent sync run for the same stream returns 409 Conflict
    conflict_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/sync-runs",
        json={"stream_name": "meters"},
    )
    assert conflict_res.status_code == 409, conflict_res.text
    assert conflict_res.json()["code"] == "ACTIVE_SYNC_RUN_EXISTS"

    # 3. List sync runs for the connection
    list_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/sync-runs"
    )
    assert list_res.status_code == 200, list_res.text
    runs = list_res.json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id

    # 4. Get sync run by ID
    get_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/sync-runs/{run_id}"
    )
    assert get_res.status_code == 200, get_res.text
    assert get_res.json()["run_id"] == run_id

    # 5. Resetting a stream with an active PENDING sync run returns 409 Conflict
    active_reset_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/streams/meters/reset"
    )
    assert active_reset_res.status_code == 409, active_reset_res.text
    assert active_reset_res.json()["code"] == "ACTIVE_SYNC_RUN_EXISTS"

    # 6. Reset stream checkpoint cursor on an idle stream -> creates/resets stream state
    reset_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/streams/interval_reads/reset"
    )
    assert reset_res.status_code == 200, reset_res.text
    state_data = reset_res.json()
    assert state_data["connection_id"] == connection_id
    assert state_data["stream_name"] == "interval_reads"
    assert state_data["cursor_value"] is None

    # 7. List stream states for the connection
    states_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/streams/state"
    )
    assert states_res.status_code == 200, states_res.text
    states = states_res.json()
    assert len(states) == 1
    assert states[0]["stream_name"] == "interval_reads"
