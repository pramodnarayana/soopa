"""Integration tests for Integration Platform Transactions, Trace Waterfall, Lineage, and Replay API routes."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


async def _create_connection_and_ingest_record(
    auth_client: httpx.AsyncClient,
    tenant_id: str,
    *,
    correlation_id: str = "CORR-MTR-900",
) -> str:
    conn_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": f"Trace Test Connection {correlation_id}",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": f"https://ami-{correlation_id.lower()}.testgrid.com"},
            "raw_credentials": {"api_key": "test_token"},
            "endpoint_for_fingerprint": f"https://ami-{correlation_id.lower()}.testgrid.com",
        },
    )
    assert conn_response.status_code == 201, conn_response.text
    connection_id: str = conn_response.json()["id"]

    ingress_response = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/ingress/{connection_id}?stream=meters",
        json={
            "meter_serial": correlation_id,
            "timestamp": "2026-10-27T08:00:00Z",
            "kwh": 42.5,
        },
        headers={"X-Correlation-ID": correlation_id},
    )
    assert ingress_response.status_code == 202, ingress_response.text
    trace_id: str = ingress_response.json()["trace_id"]
    return trace_id


@pytest.mark.asyncio
async def test_get_ip_trace_and_correlation_search(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    trace_id = await _create_connection_and_ingest_record(
        auth_client,
        tenant_id,
        correlation_id="CORR-MTR-101",
    )

    # 1. Fetch 5-layer trace waterfall
    trace_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{trace_id}",
    )
    assert trace_res.status_code == 200, trace_res.text
    trace_data = trace_res.json()
    assert trace_data["trace_id"] == trace_id
    assert trace_data["tenant_id"] == tenant_id
    assert trace_data["correlation_id"] == "CORR-MTR-101"
    assert trace_data["original_trace_id"] == trace_id
    assert trace_data["replay_count"] == 0
    assert trace_data["status"] == "INGESTED"
    assert trace_data["inbound_record"] is not None
    assert trace_data["inbound_record"]["request_body"]["meter_serial"] == "CORR-MTR-101"
    assert len(trace_data["trace_events"]) >= 1

    # 2. Search by correlation_id
    search_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/search?correlation_id=CORR-MTR-101",
    )
    assert search_res.status_code == 200, search_res.text
    search_items = search_res.json()
    assert len(search_items) >= 1
    assert any(item["trace_id"] == trace_id for item in search_items)


@pytest.mark.asyncio
async def test_get_ip_trace_unknown_returns_404(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/ip_trc_nonexistent_999",
    )
    assert res.status_code == 404, res.text
    assert res.json()["code"] == "TRACE_NOT_FOUND"


@pytest.mark.asyncio
async def test_replay_modify_and_replay_and_lineage_endpoints(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    root_trace_id = await _create_connection_and_ingest_record(
        auth_client,
        tenant_id,
        correlation_id="CORR-MTR-202",
    )

    # 1. Replay from RETRY_INGEST -> 202 Accepted
    replay_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{root_trace_id}/replay",
        json={"stage": "RETRY_INGEST"},
    )
    assert replay_res.status_code == 202, replay_res.text
    replay_data = replay_res.json()
    assert replay_data["status"] == "ACCEPTED"
    assert replay_data["original_trace_id"] == root_trace_id
    assert replay_data["parent_trace_id"] == root_trace_id
    assert replay_data["replay_count"] == 1
    child_trace_1: str = replay_data["new_trace_id"]

    # 2. Modify-and-Replay from child_trace_1 -> 202 Accepted
    mod_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{child_trace_1}/modify-and-replay",
        json={
            "stage": "RETRY_INGEST",
            "modified_payload": {
                "meter_serial": "CORR-MTR-202",
                "timestamp": "2026-10-27T09:00:00Z",
                "kwh": 99.9,
            },
        },
    )
    assert mod_res.status_code == 202, mod_res.text
    mod_data = mod_res.json()
    assert mod_data["status"] == "ACCEPTED"
    assert mod_data["original_trace_id"] == root_trace_id
    assert mod_data["parent_trace_id"] == child_trace_1
    assert mod_data["replay_count"] == 2
    child_trace_2: str = mod_data["new_trace_id"]

    # Verify modified payload was persisted on child_trace_2
    child_trace_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{child_trace_2}",
    )
    assert child_trace_res.status_code == 200, child_trace_res.text
    assert child_trace_res.json()["inbound_record"]["request_body"]["kwh"] == 99.9

    # 3. Fetch full replay lineage tree from child_trace_2
    lineage_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{child_trace_2}/lineage",
    )
    assert lineage_res.status_code == 200, lineage_res.text
    lineage_items = lineage_res.json()
    assert [item["trace_id"] for item in lineage_items] == [
        root_trace_id,
        child_trace_1,
        child_trace_2,
    ]
    assert [item["replay_count"] for item in lineage_items] == [0, 1, 2]

    # 4. Replaying an unavailable stage (e.g. RETRY_DELIVER when only L1 exists) returns 409
    bad_stage_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{root_trace_id}/replay",
        json={"stage": "RETRY_DELIVER"},
    )
    assert bad_stage_res.status_code == 409, bad_stage_res.text
    assert bad_stage_res.json()["code"] == "REPLAY_STAGE_NOT_AVAILABLE"

    # 5. Modify-and-replay with empty payload returns 400
    empty_mod_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/{root_trace_id}/modify-and-replay",
        json={"stage": "RETRY_INGEST", "modified_payload": {}},
    )
    assert empty_mod_res.status_code == 400, empty_mod_res.text
    assert empty_mod_res.json()["code"] == "INVALID_REPLAY_PAYLOAD"


@pytest.mark.asyncio
async def test_bulk_replay_transactions_endpoint(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    trace_1 = await _create_connection_and_ingest_record(
        auth_client,
        tenant_id,
        correlation_id="CORR-BULK-01",
    )
    trace_2 = await _create_connection_and_ingest_record(
        auth_client,
        tenant_id,
        correlation_id="CORR-BULK-02",
    )

    bulk_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transactions/bulk-replay",
        json={
            "trace_ids": [trace_1, trace_2, "ip_trc_missing_bulk"],
            "stage": "RETRY_INGEST",
        },
    )
    assert bulk_res.status_code == 202, bulk_res.text
    bulk_data = bulk_res.json()
    assert bulk_data["status"] == "ACCEPTED"
    assert bulk_data["stage"] == "RETRY_INGEST"
    assert bulk_data["replayed_count"] == 2
    assert bulk_data["succeeded_trace_ids"] == [trace_1, trace_2]
    assert len(bulk_data["new_trace_ids"]) == 2
    assert len(bulk_data["failed_items"]) == 1
    assert bulk_data["failed_items"][0]["trace_id"] == "ip_trc_missing_bulk"
    assert bulk_data["failed_items"][0]["error_code"] == "TRACE_NOT_FOUND"
