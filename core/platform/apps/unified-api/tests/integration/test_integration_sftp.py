import httpx
import pytest


@pytest.mark.asyncio
async def test_sftp_partners_crud(auth_client: httpx.AsyncClient, seeded_api_token: dict):
    """
    Test the SFTP Partners API on the tenant level.
    """
    tenant_id = seeded_api_token["tenant_id"]
    base_url = f"/api/v1/tenants/{tenant_id}/edi/trading-partners/sftp"

    # 1. Test SFTP Connection (Invalid - no credentials)
    res = await auth_client.post(
        f"{base_url}/test", json={"host": "sftp.example.com", "port": 22, "username": "testuser"}
    )
    assert res.status_code == 200
    assert res.json()["success"] is False

    # 2. Create SFTP Partner
    res = await auth_client.post(
        base_url,
        json={
            "name": "Integration Test SFTP",
            "host": "sftp.example.com",
            "port": 22,
            "username": "testuser",
            "credentials_vault_ref": "mock_vault_ref",
            "inbound_remote_path": "/inbound",
            "outbound_remote_path": "/outbound",
        },
    )
    assert res.status_code == 201, res.text
    partner = res.json()
    partner_id = partner["partner_id"]
    assert partner["name"] == "Integration Test SFTP"

    # 3. Update SFTP Partner
    res = await auth_client.put(
        f"{base_url}/{partner_id}",
        json={
            "name": "Updated Test SFTP",
            "host": "sftp.example.com",
            "port": 2222,
            "username": "updateduser",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Updated Test SFTP"
    assert res.json()["port"] == 2222

    # 4. Test Existing Connection
    res = await auth_client.post(
        f"{base_url}/{partner_id}/test",
        json={"host": "sftp.example.com", "port": 2222, "username": "updateduser"},
    )
    assert res.status_code == 200

    # 5. Delete SFTP Partner
    res = await auth_client.delete(f"{base_url}/{partner_id}")
    assert res.status_code == 204
