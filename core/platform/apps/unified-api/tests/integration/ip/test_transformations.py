"""Narrow PostgreSQL integration tests for IP Control Plane Transformations API routes."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


async def _create_test_connection(
    auth_client: httpx.AsyncClient,
    tenant_id: str,
    name_suffix: str,
) -> str:
    res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/connections",
        json={
            "app_id": "itron_mdm",
            "name": f"Transformation Test {name_suffix}",
            "auth_type": "API_KEY",
            "public_config": {"endpoint_url": f"https://ami-{name_suffix.lower()}.testgrid.com"},
            "raw_credentials": {"api_key": "test_token"},
            "endpoint_for_fingerprint": f"https://ami-{name_suffix.lower()}.testgrid.com",
        },
    )
    assert res.status_code == 201, res.text
    conn_id: str = res.json()["id"]
    return conn_id


@pytest.mark.asyncio
async def test_transformations_bind_list_get_promote_and_preview_lifecycle(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    connection_id = await _create_test_connection(auth_client, tenant_id, "bind-1")

    # 1. List registered code transformers
    transformers_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/transformers"
    )
    assert transformers_res.status_code == 200, transformers_res.text
    transformers = transformers_res.json()
    assert len(transformers) >= 6
    assert any(
        m["transformation_id"] == "energy.ami_meter_reading" and m["transformation_version"] == 1
        for m in transformers
    )
    assert any(
        m["transformation_id"] == "energy.ami_meter_reading" and m["transformation_version"] == 2
        for m in transformers
    )

    # 2. Bind stream transformation with v1 active + v2 shadow
    bind_res = await auth_client.put(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/connections/{connection_id}/streams/interval_reads",
        json={
            "transformation_id": "energy.ami_meter_reading",
            "transformation_version": 1,
            "mode": "ACTIVE",
            "shadow_transformation_version": 2,
        },
    )
    assert bind_res.status_code == 200, bind_res.text
    bound_data = bind_res.json()
    assert bound_data["connection_id"] == connection_id
    assert bound_data["stream"] == "interval_reads"
    assert bound_data["transformation_id"] == "energy.ami_meter_reading"
    assert bound_data["transformation_version"] == 1
    assert bound_data["mode"] == "ACTIVE"
    assert bound_data["shadow_transformation_version"] == 2

    # 3. List connection transformations
    list_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/connections/{connection_id}"
    )
    assert list_res.status_code == 200, list_res.text
    bindings = list_res.json()
    assert len(bindings) == 1
    assert bindings[0]["stream"] == "interval_reads"

    # 4. Get single stream transformation
    get_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/connections/{connection_id}/streams/interval_reads"
    )
    assert get_res.status_code == 200, get_res.text
    assert get_res.json()["shadow_transformation_version"] == 2

    # 5. Preview dry-run with active v1 and shadow v2 diff
    preview_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/preview",
        json={
            "connection_id": connection_id,
            "stream": "interval_reads",
            "transformation_id": "energy.ami_meter_reading",
            "transformation_version": 1,
            "record_key": "MTR-700",
            "sample_payload": {
                "meter_id": "MTR-700",
                "kwh_delivered": 84.5,
                "kwh_received": 4.5,
                "timestamp": "2026-10-27T12:00:00Z",
                "quality": "ESTIMATED",
            },
            "shadow_transformation_version": 2,
        },
    )
    assert preview_res.status_code == 200, preview_res.text
    preview_data = preview_res.json()
    assert len(preview_data["drafts"]) == 1
    assert preview_data["drafts"][0]["source_id"] == "MTR-700"
    assert preview_data["shadow_transformation_version"] == 2
    assert len(preview_data["shadow_diffs"]) >= 1

    # 6. Promote shadow version v2 to active
    promote_res = await auth_client.post(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/connections/{connection_id}/streams/interval_reads/promote"
    )
    assert promote_res.status_code == 200, promote_res.text
    promo_data = promote_res.json()
    assert promo_data["promoted_version"] == 2
    assert promo_data["previous_version"] == 1

    # 7. Verify active version is now 2 and shadow_transformation_version is cleared
    after_get_res = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/ip/transformations/connections/{connection_id}/streams/interval_reads"
    )
    assert after_get_res.status_code == 200, after_get_res.text
    after_data = after_get_res.json()
    assert after_data["transformation_version"] == 2
    assert after_data["shadow_transformation_version"] is None
