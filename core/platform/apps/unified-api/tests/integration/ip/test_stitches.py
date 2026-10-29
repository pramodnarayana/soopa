"""Narrow PostgreSQL integration tests for IP Control Plane Stitches & Durable Workflows API routes."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_stitches_definitions_subscriptions_dispatch_and_run_inspection(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    # 1. List registered Stitch WorkflowDefinition DAGs
    defs_res = await auth_client.get(f"/api/v1/tenants/{tenant_id}/ip/stitches/definitions")
    assert defs_res.status_code == 200, defs_res.text
    defs = defs_res.json()
    assert len(defs) >= 3
    workflow_ids = {d["workflow_id"] for d in defs}
    assert "energy.outage_restoration_stitch" in workflow_ids
    assert "energy.meter_reading_erp_sync_stitch" in workflow_ids
    assert "tms.load_tender_erp_sync_stitch" in workflow_ids

    # 2. Get specific Stitch WorkflowDefinition DAG
    get_def_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/stitches/definitions/energy.outage_restoration_stitch"
    )
    assert get_def_res.status_code == 200, get_def_res.text
    outage_def = get_def_res.json()
    assert outage_def["workflow_id"] == "energy.outage_restoration_stitch"
    assert outage_def["version"] == 1
    assert [n["node_key"] for n in outage_def["nodes"]] == [
        "lookup_meter_replica",
        "wait_restored",
        "notify_grid_ops",
    ]

    # 3. List default Stitches
    subs_res = await auth_client.get(f"/api/v1/tenants/{tenant_id}/ip/stitches")
    assert subs_res.status_code == 200, subs_res.text
    subs = subs_res.json()
    assert len(subs) >= 2

    # 4. Register a tenant-specific Stitch
    create_sub_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/stitches",
        json={
            "stitch_id": "sub_tenant_load_tender_v1",
            "workflow_id": "tms.load_tender_erp_sync_stitch",
            "workflow_version": 1,
            "canonical_event_type": "canonical.vip_load_tender.normalized",
            "is_trigger": True,
            "idempotency_key_field": "load_id",
            "concurrency_key_field": "carrier_id",
        },
    )
    assert create_sub_res.status_code == 201, create_sub_res.text
    created_sub = create_sub_res.json()
    assert created_sub["id"] == "sub_tenant_load_tender_v1"
    assert created_sub["tenant_id"] == tenant_id

    # 5. Dispatch canonical event to trigger durable Stitch run on tenant Data Plane shard
    dispatch_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/stitches/dispatch",
        json={
            "canonical_event_type": "canonical.vip_load_tender.normalized",
            "payload": {
                "load_id": "VIP-LD-900",
                "carrier_id": "CAR-VIP-01",
                "rate_usd": 3500.0,
            },
            "correlation_id": "VIP-LD-900",
        },
    )
    assert dispatch_res.status_code == 202, dispatch_res.text
    dispatch_data = dispatch_res.json()
    assert len(dispatch_data["started_run_ids"]) == 1
    run_id = dispatch_data["started_run_ids"][0]
    assert run_id.startswith("wf_run_")

    # 6. Duplicate dispatch with same idempotency key is deduplicated
    dup_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/stitches/dispatch",
        json={
            "canonical_event_type": "canonical.vip_load_tender.normalized",
            "payload": {
                "load_id": "VIP-LD-900",
                "carrier_id": "CAR-VIP-01",
                "rate_usd": 3500.0,
            },
            "correlation_id": "VIP-LD-900",
        },
    )
    assert dup_res.status_code == 202, dup_res.text
    dup_data = dup_res.json()
    assert dup_data["started_run_ids"] == []
    assert dup_data["deduplicated_run_ids"] == [run_id]

    # 7. Inspect the persisted WorkflowRun and StepRuns on the tenant shard
    run_res = await auth_client.get(f"/api/v1/tenants/{tenant_id}/ip/stitches/runs/{run_id}")
    assert run_res.status_code == 200, run_res.text
    run_data = run_res.json()
    assert run_data["run_id"] == run_id
    assert run_data["tenant_id"] == tenant_id
    assert run_data["workflow_id"] == "tms.load_tender_erp_sync_stitch"
    assert run_data["correlation_id"] == "VIP-LD-900"
    assert len(run_data["steps"]) == 3
    step_keys = {s["node_key"] for s in run_data["steps"]}
    assert step_keys == {
        "lookup_carrier_replica",
        "dispatch_erp_invoice",
        "notify_logistics_ops",
    }
