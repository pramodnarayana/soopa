import httpx
import pytest


@pytest.mark.asyncio
async def test_platform_as2_partners_crud(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    """
    Test the AS2 Partners API on the Platform admin level.
    """
    # 1. List AS2 Partners
    res = await auth_client.get("/api/v1/platform/trading-partners/as2/trading-partners")
    assert res.status_code == 200

    # 2. Create a local AS2 partner
    res = await auth_client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={
            "name": "Integration Test Local AS2",
            "as2_id": "INT_TEST_LOCAL_AS2",
            "is_local": True,
        },
    )
    assert res.status_code == 201
    partner = res.json()
    partner_id = partner["id"]
    assert partner["name"] == "Integration Test Local AS2"
    assert partner["as2_id"] == "INT_TEST_LOCAL_AS2"
    assert partner["is_local"] is True

    # 3. Create a remote AS2 partner
    res = await auth_client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={
            "name": "Integration Test Remote AS2",
            "as2_id": "INT_TEST_REMOTE_AS2",
            "is_local": False,
            "url": "http://remote-as2.example.com",
        },
    )
    assert res.status_code == 201
    remote_partner = res.json()
    remote_partner_id = remote_partner["id"]

    # 4. Update the remote partner
    res = await auth_client.put(
        f"/api/v1/platform/trading-partners/as2/trading-partners/{remote_partner_id}",
        json={
            "name": "Updated Remote AS2",
            "as2_id": "INT_TEST_REMOTE_AS2_UPDATED",
            "is_local": False,
            "url": "http://updated.example.com",
            "active": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Remote AS2"

    # 5. Delete the remote partner
    res = await auth_client.delete(
        f"/api/v1/platform/trading-partners/as2/trading-partners/{remote_partner_id}"
    )
    assert res.status_code == 204

    # 6. Delete the local partner
    res = await auth_client.delete(
        f"/api/v1/platform/trading-partners/as2/trading-partners/{partner_id}"
    )
    assert res.status_code == 204
