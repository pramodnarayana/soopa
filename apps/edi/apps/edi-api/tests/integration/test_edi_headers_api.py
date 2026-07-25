import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_edi_header_lifecycle(client: AsyncClient):
    """
    Tests the creation, listing, updating (PATCH), and deletion of
    Outbound EDI Headers in the Tenant Data Plane.
    """
    # 1. Create Outbound EDI Header
    payload = {
        "name": f"Header {str(uuid.uuid4())[:6]}",
        "trading_partner_id": f"TP_{str(uuid.uuid4())[:8]}",
        "isa_sender_id": "SENDER01",
        "isa_sender_qualifier": "ZZ",
        "isa_receiver_id": "RECEIVER01",
        "isa_receiver_qualifier": "ZZ",
        "gs_sender_id": "GS_SENDER",
        "gs_receiver_id": "GS_RECEIVER",
        "transaction_type": "850",
        "default_standard": "X12",
        "default_version": "00401",
    }
    res_create = await client.post("/api/v1/edi-headers", json=payload)
    assert res_create.status_code == 201, f"Failed to create EDI header: {res_create.text}"
    created_data = res_create.json()
    assert "id" in created_data
    header_id = created_data["id"]

    # 2. List EDI Headers and verify presence
    res_list = await client.get("/api/v1/edi-headers")
    assert res_list.status_code == 200, f"Failed to list EDI headers: {res_list.text}"
    headers = res_list.json()
    matching = [h for h in headers if h["id"] == header_id]
    assert len(matching) == 1, "Created EDI header not found in list"
    header = matching[0]
    assert header["name"] == payload["name"]
    assert header["isa_sender_id"] == "SENDER01"
    assert header["gs_receiver_id"] == "GS_RECEIVER"
    assert header["transaction_type"] == "850"

    # 3. Update EDI Header (PATCH)
    patch_payload = {
        "name": f"Updated Header {str(uuid.uuid4())[:6]}",
        "default_version": "00501",
    }
    res_patch = await client.patch(f"/api/v1/edi-headers/{header_id}", json=patch_payload)
    assert res_patch.status_code == 200, f"Failed to update EDI header: {res_patch.text}"
    assert res_patch.json() == {"status": "ok"}

    # 4. Verify update by listing again
    res_list_after = await client.get("/api/v1/edi-headers")
    assert res_list_after.status_code == 200
    updated_matching = [h for h in res_list_after.json() if h["id"] == header_id]
    assert len(updated_matching) == 1
    assert updated_matching[0]["name"] == patch_payload["name"]
    assert updated_matching[0]["default_version"] == "00501"

    # 5. Delete EDI Header
    res_delete = await client.delete(f"/api/v1/edi-headers/{header_id}")
    assert res_delete.status_code == 204, f"Failed to delete EDI header: {res_delete.text}"

    # 6. Verify deletion
    res_list_final = await client.get("/api/v1/edi-headers")
    assert res_list_final.status_code == 200
    assert not any(h["id"] == header_id for h in res_list_final.json())


async def test_edi_header_not_found(client: AsyncClient):
    """
    Tests PATCH and DELETE on a non-existent EDI header ID return 404.
    """
    fake_id = str(uuid.uuid4())
    res_patch = await client.patch(f"/api/v1/edi-headers/{fake_id}", json={"name": "New Name"})
    assert res_patch.status_code == 404

    res_delete = await client.delete(f"/api/v1/edi-headers/{fake_id}")
    assert res_delete.status_code == 404
