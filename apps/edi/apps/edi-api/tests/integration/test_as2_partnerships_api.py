import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_as2_partnership_lifecycle(platform_client: AsyncClient):
    """
    Tests the creation, retrieval, and listing of an AS2 Partnership
    between a local trading partner and a remote trading partner.
    """
    # 1. Create Local AS2 Partner
    local_payload = {
        "name": f"Local Gateway {str(uuid.uuid4())[:6]}",
        "as2_id": f"LOCAL_{str(uuid.uuid4())[:8]}",
        "is_local": True,
        "url": "http://local.example.com/as2",
    }
    res_local = await platform_client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners", json=local_payload
    )
    assert res_local.status_code == 201, f"Failed to create local AS2 partner: {res_local.text}"
    local_partner = res_local.json()
    local_id = local_partner["id"]

    # 2. Create Remote AS2 Partner
    remote_payload = {
        "name": f"Remote Partner {str(uuid.uuid4())[:6]}",
        "as2_id": f"REMOTE_{str(uuid.uuid4())[:8]}",
        "is_local": False,
        "url": "http://remote.partner.com/as2",
    }
    res_remote = await platform_client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners", json=remote_payload
    )
    assert res_remote.status_code == 201, f"Failed to create remote AS2 partner: {res_remote.text}"
    remote_partner = res_remote.json()
    remote_id = remote_partner["id"]

    # 3. Create AS2 Partnership
    partnership_payload = {
        "name": f"Partnership {local_payload['as2_id']} -> {remote_payload['as2_id']}",
        "local_partner_id": local_id,
        "remote_partner_id": remote_id,
        "mdn_type": "SYNC",
        "encryption_algorithm": "AES256",
        "signature_algorithm": "SHA256",
    }
    res_partnership = await platform_client.post(
        "/api/v1/platform/trading-partners/as2/partnerships", json=partnership_payload
    )
    assert (
        res_partnership.status_code == 201
    ), f"Failed to create AS2 partnership: {res_partnership.text}"
    partnership = res_partnership.json()
    assert partnership["name"] == partnership_payload["name"]
    assert partnership["local_partner_id"] == local_id
    assert partnership["remote_partner_id"] == remote_id
    assert partnership["mdn_type"] == "SYNC"
    partnership_id = partnership["id"]

    # 4. List AS2 Partnerships and verify creation
    res_list = await platform_client.get("/api/v1/platform/trading-partners/as2/partnerships")
    assert res_list.status_code == 200
    partnerships_list = res_list.json()
    assert any(p["id"] == partnership_id for p in partnerships_list)

    # 5. Update AS2 Partnership (PUT)
    update_payload = {
        "name": f"Updated Partnership {local_payload['as2_id']}",
        "mdn_type": "ASYNC",
        "mdn_url": "http://mdn.example.com/receiver",
    }
    res_put = await platform_client.put(
        f"/api/v1/platform/trading-partners/as2/partnerships/{partnership_id}",
        json=update_payload,
    )
    assert res_put.status_code == 200, f"Failed to update AS2 partnership: {res_put.text}"
    updated = res_put.json()
    assert updated["name"] == update_payload["name"]
    assert updated["mdn_type"] == "ASYNC"

    # 6. Delete AS2 Partnership (DELETE)
    res_del = await platform_client.delete(
        f"/api/v1/platform/trading-partners/as2/partnerships/{partnership_id}"
    )
    assert res_del.status_code == 204, f"Failed to delete AS2 partnership: {res_del.text}"

    # 7. List again and verify deletion
    res_list_after = await platform_client.get("/api/v1/platform/trading-partners/as2/partnerships")
    assert res_list_after.status_code == 200
    assert not any(p["id"] == partnership_id for p in res_list_after.json())


async def test_as2_partnership_validation_error(platform_client: AsyncClient):
    """
    Tests that creating a partnership with non-existent partner IDs fails with an error.
    """
    fake_id_1 = str(uuid.uuid4())
    fake_id_2 = str(uuid.uuid4())
    bad_payload = {
        "name": "Invalid Partnership",
        "local_partner_id": fake_id_1,
        "remote_partner_id": fake_id_2,
        "mdn_type": "SYNC",
    }
    response = await platform_client.post(
        "/api/v1/platform/trading-partners/as2/partnerships", json=bad_payload
    )
    assert response.status_code in (
        400,
        404,
        422,
        500,
    ), f"Expected failure for non-existent partners, got {response.status_code}"
