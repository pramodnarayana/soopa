import uuid
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from identity.domain.identity_context import PLATFORM_TENANT_ID

from unified_api.adapters.inbound.http.dependencies.edi.services import get_as2_tester

pytestmark = pytest.mark.integration


class _StubAs2Tester:
    def __init__(
        self,
        responder: Callable[[], tuple[bool, str | None, str | None, str | None]],
    ) -> None:
        self._responder = responder
        self.last_custom_payload: str | None = None

    async def test_connection(
        self,
        remote_url: str,
        as2_from: str,
        as2_to: str,
        local_private_key_pem: bytes | None,
        local_cert_pem: bytes | None,
        remote_cert_pem: bytes | None,
        encryption_algorithm: str,
        signature_algorithm: str,
        custom_payload: str | None = None,
    ) -> tuple[bool, str | None, str | None, str | None]:
        _ = (
            remote_url,
            as2_from,
            as2_to,
            local_private_key_pem,
            local_cert_pem,
            remote_cert_pem,
            encryption_algorithm,
            signature_algorithm,
        )
        self.last_custom_payload = custom_payload
        return self._responder()


@pytest.mark.asyncio
async def test_global_as2_partners_crud(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    _ = seeded_api_token
    res = await auth_client.get("/api/v1/as2/trading-partners")
    assert res.status_code == 200

    res = await auth_client.post(
        "/api/v1/as2/trading-partners",
        json={
            "name": "Integration Test Local AS2",
            "as2_id": "INT_TEST_LOCAL_AS2",
            "is_local": True,
            "private_key_vault_ref": "sec_dummy_vault_ref",
        },
    )
    assert res.status_code == 201
    partner = res.json()
    partner_id = partner["id"]
    assert partner["name"] == "Integration Test Local AS2"
    assert partner["as2_id"] == "INT_TEST_LOCAL_AS2"
    assert partner["is_local"] is True

    res = await auth_client.post(
        "/api/v1/as2/trading-partners",
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

    res = await auth_client.put(
        f"/api/v1/as2/trading-partners/{remote_partner_id}",
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

    res = await auth_client.delete(f"/api/v1/as2/trading-partners/{remote_partner_id}")
    assert res.status_code == 204

    res = await auth_client.delete(f"/api/v1/as2/trading-partners/{partner_id}")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_as2_settings_and_certificate_lifecycle(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, str],
) -> None:
    tenant_id = seeded_api_token["tenant_id"]

    settings_res = await auth_client.get("/api/v1/as2/settings")
    assert settings_res.status_code == 200
    settings_body = settings_res.json()
    assert len(settings_body["supported_as2_encryption_algorithms"]) >= 2
    assert len(settings_body["supported_as2_signature_algorithms"]) >= 2

    gen_orphan = await auth_client.post(
        "/api/v1/as2/certificates/generate",
        json={"as2_id": "ORPHAN_CERT_STATION"},
    )
    assert gen_orphan.status_code == 200
    orphan_ref = gen_orphan.json()["private_key_vault_ref"]
    assert "BEGIN CERTIFICATE" in gen_orphan.json()["public_cert_pem"]

    bad_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": "invalid_ref_without_scheme"},
    )
    assert bad_del.status_code == 400

    traversal_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": "as2_key/../sftp_key/secret_123"},
    )
    assert traversal_del.status_code == 400

    nested_wrong_category_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": "as2_key/other_category/secret_123"},
    )
    assert nested_wrong_category_del.status_code == 400

    foreign_prefix_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": "foreign_prefix/as2_key/gen_123"},
    )
    assert foreign_prefix_del.status_code == 400

    ok_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": orphan_ref},
    )
    assert ok_del.status_code == 204

    unique_suffix = uuid.uuid4().hex[:8].upper()
    active_as2_id = f"ACTIVE_CERT_{unique_suffix}"
    cert_managed_local_id = f"CERT_LOCAL_{unique_suffix}"
    remote_cert_export_id = f"REMOTE_CERT_{unique_suffix}"

    gen_active = await auth_client.post(
        "/api/v1/as2/certificates/generate",
        json={"as2_id": active_as2_id},
    )
    assert gen_active.status_code == 200
    active_cert_pem = gen_active.json()["public_cert_pem"]
    active_key_ref = gen_active.json()["private_key_vault_ref"]

    local_res = await auth_client.post(
        "/api/v1/as2/trading-partners",
        json={
            "name": "Cert Managed Local Station",
            "as2_id": cert_managed_local_id,
            "is_local": True,
            "url": "http://local-as2.example.com/as2/inbox",
            "public_cert_pem": active_cert_pem,
            "private_key_vault_ref": active_key_ref,
        },
    )
    assert local_res.status_code == 201
    local_partner_id = local_res.json()["id"]

    in_use_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": active_key_ref},
    )
    assert in_use_del.status_code == 400

    alias_scheme_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": f"vault://{active_key_ref}"},
    )
    assert alias_scheme_del.status_code == 400

    alias_slash_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": f"/{active_key_ref}/"},
    )
    assert alias_slash_del.status_code == 400

    export_missing = await auth_client.get("/api/v1/as2/certificates/as2p_nonexistent/export")
    assert export_missing.status_code == 404

    export_local = await auth_client.get(f"/api/v1/as2/certificates/{local_partner_id}/export")
    assert export_local.status_code == 200
    assert export_local.json()["private_key_pem"] is not None

    rotate_missing = await auth_client.put(
        "/api/v1/as2/certificates/as2p_nonexistent/rotate",
        json={"action": "generate"},
    )
    assert rotate_missing.status_code == 404

    rotate_local = await auth_client.put(
        f"/api/v1/as2/certificates/{local_partner_id}/rotate",
        json={"action": "generate"},
    )
    assert rotate_local.status_code == 200

    prev_in_use_alias_del = await auth_client.delete(
        "/api/v1/as2/certificates/secret",
        params={"vault_ref": f"vault://{active_key_ref}"},
    )
    assert prev_in_use_alias_del.status_code == 400

    export_rotated = await auth_client.get(f"/api/v1/as2/certificates/{local_partner_id}/export")
    assert export_rotated.status_code == 200
    assert export_rotated.json()["prev_private_key_pem"] is not None

    tenant_partners = await auth_client.get(f"/api/v1/tenants/{tenant_id}/edi/trading-partners")
    assert tenant_partners.status_code == 200
    assert any(p["partner_id"] == local_partner_id for p in tenant_partners.json())

    tenant_export_missing = await auth_client.get(
        f"/api/v1/tenants/{tenant_id}/edi/trading-partners/as2/as2p_missing/certificates/export"
    )
    assert tenant_export_missing.status_code == 404

    tenant_rotate_missing = await auth_client.put(
        f"/api/v1/tenants/{tenant_id}/edi/trading-partners/as2/certificates/as2p_missing/rotate",
        json={"action": "generate"},
    )
    assert tenant_rotate_missing.status_code == 404

    platform_partners = await auth_client.get(
        f"/api/v1/tenants/{PLATFORM_TENANT_ID}/edi/trading-partners"
    )
    assert platform_partners.status_code == 200

    tenant_export_local_forbidden = await auth_client.get(
        f"/api/v1/tenants/{PLATFORM_TENANT_ID}/edi/trading-partners/as2/{local_partner_id}/certificates/export"
    )
    assert tenant_export_local_forbidden.status_code == 403

    tenant_rotate_local_forbidden = await auth_client.put(
        f"/api/v1/tenants/{PLATFORM_TENANT_ID}/edi/trading-partners/as2/certificates/{local_partner_id}/rotate",
        json={"action": "generate"},
    )
    assert tenant_rotate_local_forbidden.status_code == 403

    remote_cert_partner = await auth_client.post(
        "/api/v1/as2/trading-partners",
        json={
            "name": "Remote Cert Export Partner",
            "as2_id": remote_cert_export_id,
            "is_local": False,
            "url": "http://remote-cert.example.com/as2",
            "public_cert_pem": active_cert_pem,
        },
    )
    assert remote_cert_partner.status_code == 201
    remote_cert_id = remote_cert_partner.json()["id"]

    tenant_export_remote_ok = await auth_client.get(
        f"/api/v1/tenants/{PLATFORM_TENANT_ID}/edi/trading-partners/as2/{remote_cert_id}/certificates/export"
    )
    assert tenant_export_remote_ok.status_code == 200
    assert tenant_export_remote_ok.json()["public_cert_pem"] is not None

    upd_missing_partner = await auth_client.put(
        "/api/v1/as2/trading-partners/as2p_missing",
        json={"name": "Missing AS2 Partner", "active": False},
    )
    assert upd_missing_partner.status_code == 404


@pytest.mark.asyncio
async def test_as2_partnerships_lifecycle_and_connection_test(
    app: FastAPI,
    auth_client: httpx.AsyncClient,
) -> None:
    ps_suffix = uuid.uuid4().hex[:8].upper()
    ps_local_id = f"PS_LOCAL_{ps_suffix}"
    ps_remote_id = f"PS_REMOTE_{ps_suffix}"
    ps_remote_no_url_id = f"PS_NO_URL_{ps_suffix}"

    gen_res = await auth_client.post(
        "/api/v1/as2/certificates/generate",
        json={"as2_id": ps_local_id},
    )
    assert gen_res.status_code == 200

    local_partner_res = await auth_client.post(
        "/api/v1/as2/trading-partners",
        json={
            "name": "PS Local Station",
            "as2_id": ps_local_id,
            "is_local": True,
            "url": "http://local-station.example.com/as2/inbox",
            "public_cert_pem": gen_res.json()["public_cert_pem"],
            "private_key_vault_ref": gen_res.json()["private_key_vault_ref"],
        },
    )
    assert local_partner_res.status_code == 201
    local_id = local_partner_res.json()["id"]

    remote_partner_res = await auth_client.post(
        "/api/v1/as2/trading-partners",
        json={
            "name": "PS Remote Partner",
            "as2_id": ps_remote_id,
            "is_local": False,
            "url": "http://remote-station.example.com/as2/inbox",
            "public_cert_pem": gen_res.json()["public_cert_pem"],
        },
    )
    assert remote_partner_res.status_code == 201
    remote_id = remote_partner_res.json()["id"]

    remote_no_url_res = await auth_client.post(
        "/api/v1/as2/trading-partners",
        json={
            "name": "PS Remote No URL",
            "as2_id": ps_remote_no_url_id,
            "is_local": False,
        },
    )
    assert remote_no_url_res.status_code == 201
    remote_no_url_id = remote_no_url_res.json()["id"]

    create_ps_res = await auth_client.post(
        "/api/v1/as2/partnerships",
        json={
            "name": "Primary AS2 Partnership",
            "local_partner_id": local_id,
            "remote_partner_id": remote_id,
            "mdn_type": "SYNC",
            "encryption_algorithm": "AES256",
            "signature_algorithm": "SHA256",
        },
    )
    assert create_ps_res.status_code == 201
    partnership_id = create_ps_res.json()["id"]

    create_no_url_ps = await auth_client.post(
        "/api/v1/as2/partnerships",
        json={
            "name": "No URL Partnership",
            "local_partner_id": local_id,
            "remote_partner_id": remote_no_url_id,
            "mdn_type": "SYNC",
            "encryption_algorithm": "AES256",
            "signature_algorithm": "SHA256",
        },
    )
    assert create_no_url_ps.status_code == 201
    no_url_ps_id = create_no_url_ps.json()["id"]

    list_res = await auth_client.get("/api/v1/as2/partnerships")
    assert list_res.status_code == 200
    assert any(p["id"] == partnership_id for p in list_res.json())

    upd_res = await auth_client.put(
        f"/api/v1/as2/partnerships/{partnership_id}",
        json={
            "name": "Updated AS2 Partnership",
            "mdn_type": "SYNC",
            "encryption_algorithm": "AES128",
            "signature_algorithm": "SHA256",
            "active": True,
        },
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["name"] == "Updated AS2 Partnership"

    upd_missing = await auth_client.put(
        "/api/v1/as2/partnerships/as2ps_missing",
        json={"name": "Missing"},
    )
    assert upd_missing.status_code == 404

    test_missing = await auth_client.post("/api/v1/as2/partnerships/as2ps_missing/test")
    assert test_missing.status_code == 404

    test_no_url = await auth_client.post(f"/api/v1/as2/partnerships/{no_url_ps_id}/test")
    assert test_no_url.status_code == 200
    assert test_no_url.json()["success"] is False
    assert "no URL configured" in test_no_url.json()["reason"]

    edi_sub_app: FastAPI | None = app.state.edi_app
    assert edi_sub_app is not None

    state: dict[str, tuple[bool, str | None, str | None, str | None]] = {
        "result": (
            True,
            "automatic-action/MDN-sent-automatically; processed",
            "ISA*00*PING~",
            "MDN-RAW-OK",
        )
    }
    stub_tester = _StubAs2Tester(lambda: state["result"])
    edi_sub_app.dependency_overrides[get_as2_tester] = lambda: stub_tester
    try:
        ping_ok = await auth_client.post(
            f"/api/v1/as2/partnerships/{partnership_id}/test",
            json={"custom_payload": "ISA*00*PING~"},
        )
        assert ping_ok.status_code == 200
        assert ping_ok.json()["success"] is True
        assert ping_ok.json()["mdn_disposition"] == "processed"
        assert stub_tester.last_custom_payload == "ISA*00*PING~"

        state["result"] = (
            True,
            "automatic-action/MDN-sent-automatically; processed/error: authentication-failed",
            "ISA*00*PING~",
            "MDN-RAW-ERR",
        )
        ping_mdn_err = await auth_client.post(f"/api/v1/as2/partnerships/{partnership_id}/test")
        assert ping_mdn_err.status_code == 200
        assert ping_mdn_err.json()["success"] is False

        state["result"] = (False, "Remote host unreachable", "ISA*00*PING~", None)
        ping_transport_err = await auth_client.post(
            f"/api/v1/as2/partnerships/{partnership_id}/test"
        )
        assert ping_transport_err.status_code == 200
        assert ping_transport_err.json()["success"] is False
    finally:
        edi_sub_app.dependency_overrides.pop(get_as2_tester, None)

    del_res = await auth_client.delete(f"/api/v1/as2/partnerships/{partnership_id}")
    assert del_res.status_code == 204
    await auth_client.delete(f"/api/v1/as2/partnerships/{no_url_ps_id}")

    # Idempotent delete on missing partnership returns 204
    del_missing = await auth_client.delete("/api/v1/as2/partnerships/as2ps_missing")
    assert del_missing.status_code == 204
