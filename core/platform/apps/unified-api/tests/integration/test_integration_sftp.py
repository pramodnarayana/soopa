from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI

from unified_api.adapters.inbound.http.dependencies.edi.services import get_sftp_tester

pytestmark = pytest.mark.integration


class _StubSftpTester:
    def __init__(self, responder: Callable[[], tuple[bool, str | None]]) -> None:
        self._responder = responder

    async def test_connection(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        client_key_string: str | None = None,
    ) -> tuple[bool, str | None]:
        _ = (host, port, username, password, client_key_string)
        return self._responder()


@pytest.mark.asyncio
async def test_sftp_partners_crud_and_security_guards(
    app: FastAPI,
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]
    base_url = f"/api/v1/tenants/{tenant_id}/edi/trading-partners/sftp"

    # 1. Test SFTP Connection (Invalid - no credentials)
    res = await auth_client.post(
        f"{base_url}/test",
        json={"host": "sftp.example.com", "port": 22, "username": "testuser"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is False

    # 2. SSRF protection blocks loopback/private addresses
    ssrf_res = await auth_client.post(
        f"{base_url}/test",
        json={
            "host": "127.0.0.1",
            "port": 22,
            "username": "testuser",
            "password": "secret-password",
        },
    )
    assert ssrf_res.status_code == 200
    assert ssrf_res.json()["success"] is False
    assert "SSRF blocked" in ssrf_res.json()["reason"]

    # 3. Tenant isolation violation on foreign vault reference
    vault_violation_res = await auth_client.post(
        f"{base_url}/test",
        json={
            "host": "8.8.8.8",
            "port": 22,
            "username": "testuser",
            "credentials_vault_ref": "ten_other_tenant/ssh_key_1",
        },
    )
    assert vault_violation_res.status_code == 200
    assert vault_violation_res.json()["success"] is False
    assert "Tenant isolation violation" in vault_violation_res.json()["reason"]

    # 4. Create SFTP Partner without credentials returns 400
    missing_creds = await auth_client.post(
        base_url,
        json={
            "name": "Missing Creds SFTP",
            "host": "sftp.example.com",
            "port": 22,
            "username": "testuser",
        },
    )
    assert missing_creds.status_code == 400

    # 5. Create SFTP Partner
    res = await auth_client.post(
        base_url,
        json={
            "name": "Integration Test SFTP",
            "host": "sftp.example.com",
            "port": 22,
            "username": "testuser",
            "credentials_vault_ref": "fake_vault_ref",
            "inbound_remote_path": "/inbound",
            "outbound_remote_path": "/outbound",
        },
    )
    assert res.status_code == 201, res.text
    partner = res.json()
    partner_id = partner["partner_id"]
    assert partner["name"] == "Integration Test SFTP"

    # 6. List Tenant Trading Partners includes SFTP partner
    all_partners = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/trading-partners")
    assert all_partners.status_code == 200
    assert any(p["partner_id"] == partner_id for p in all_partners.json())

    # 7. Update SFTP Partner
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

    # 8. Test Existing Connection & SFTP Tester Paths
    edi_sub_app: FastAPI | None = app.state.edi_app
    assert edi_sub_app is not None
    edi_sub_app.dependency_overrides[get_sftp_tester] = lambda: _StubSftpTester(
        lambda: (True, None)
    )
    try:
        direct_ok = await auth_client.post(
            f"{base_url}/test",
            json={
                "host": "8.8.8.8",
                "port": 22,
                "username": "testuser",
                "password": "secret-password",
            },
        )
        assert direct_ok.status_code == 200
        assert direct_ok.json()["success"] is True

        missing_vault_key = await auth_client.post(
            f"{base_url}/test",
            json={
                "host": "8.8.8.8",
                "port": 22,
                "username": "testuser",
                "credentials_vault_ref": f"{tenant_id}/nonexistent_ssh_key",
            },
        )
        assert missing_vault_key.status_code == 200
        assert missing_vault_key.json()["success"] is False

        pw_partner_res = await auth_client.post(
            base_url,
            json={
                "name": "Password SFTP Partner",
                "host": "8.8.8.8",
                "port": 22,
                "username": "pwuser",
                "password": "stored-sftp-password",
            },
        )
        assert pw_partner_res.status_code == 201, pw_partner_res.text
        pw_partner_id = pw_partner_res.json()["partner_id"]

        existing_pw_ok = await auth_client.post(
            f"{base_url}/{pw_partner_id}/test",
            json={"host": "8.8.8.8", "port": 22, "username": "pwuser"},
        )
        assert existing_pw_ok.status_code == 200
        assert existing_pw_ok.json()["success"] is True

        existing_vault_missing = await auth_client.post(
            f"{base_url}/{partner_id}/test",
            json={"host": "8.8.8.8", "port": 2222, "username": "updateduser"},
        )
        assert existing_vault_missing.status_code == 200
        assert existing_vault_missing.json()["success"] is False

        missing_partner_test = await auth_client.post(
            f"{base_url}/sftp_missing_partner/test",
            json={"host": "8.8.8.8", "port": 22, "username": "nobody"},
        )
        assert missing_partner_test.status_code == 200
        assert missing_partner_test.json()["success"] is False

        await auth_client.delete(f"{base_url}/{pw_partner_id}")
    finally:
        edi_sub_app.dependency_overrides.pop(get_sftp_tester, None)

    upd_missing = await auth_client.put(
        f"{base_url}/sftp_missing_partner",
        json={"name": "Missing SFTP", "host": "sftp.example.com", "port": 22, "username": "u"},
    )
    assert upd_missing.status_code == 404

    # 9. Delete SFTP Partner (and idempotent delete when already removed)
    res = await auth_client.delete(f"{base_url}/{partner_id}")
    assert res.status_code == 204
    del_again = await auth_client.delete(f"{base_url}/{partner_id}")
    assert del_again.status_code == 204
