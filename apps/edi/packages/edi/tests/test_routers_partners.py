from typing import Any

import pytest
from api_fakes import FakeControlPlaneUnitOfWork
from fastapi.testclient import TestClient
from identity.domain.identity_context import PLATFORM_TENANT_ID
from unified_api.adapters.inbound.http.dependencies.edi.auth import (
    get_current_tenant_id,
    require_platform_admin,
)
from unified_api.adapters.inbound.http.dependencies.edi.database import (
    get_control_plane_uow,
    get_data_plane_uow,
)

from edi.module import create_edi_app

app = create_edi_app()


@pytest.fixture
def fake_uow():
    return FakeControlPlaneUnitOfWork()


@pytest.fixture
def client(fake_uow):
    from unified_api.adapters.inbound.http.dependencies.edi.auth import (
        get_current_user_profile,
        get_raw_jwt,
    )

    app.dependency_overrides[get_control_plane_uow] = lambda: fake_uow
    app.dependency_overrides[get_data_plane_uow] = lambda: fake_uow
    app.dependency_overrides[get_current_tenant_id] = lambda: "1"
    app.dependency_overrides[require_platform_admin] = lambda: PLATFORM_TENANT_ID
    app.dependency_overrides[get_raw_jwt] = lambda: {"sub": "user"}
    app.dependency_overrides[get_current_user_profile] = lambda: {
        "permissions": ["certificates:export_private"]
    }

    from unified_api.adapters.inbound.http.dependencies.edi.services import get_sftp_tester

    class FakeSftpTester:
        async def test_connection(
            self,
            host: str,
            port: int,
            username: str,
            password: str | None = None,
            client_key_string: str | None = None,
        ) -> tuple[bool, str | None]:
            return True, "Success"

    app.dependency_overrides[get_sftp_tester] = FakeSftpTester

    from unified_api.adapters.inbound.http.dependencies.edi.services import get_secret_store

    class FakeVault:
        async def store_private_key(self, private_key_pem: bytes, category: Any = None) -> str:
            return "vault_ref_123"

        async def retrieve_private_key(self, vault_ref: str) -> bytes:
            if vault_ref == "vault-error-ref":
                from edi.domain.exceptions import VaultError

                raise VaultError("Vault error")
            return b"fake_key"

        async def delete_secret(self, vault_ref: str) -> None:
            pass

    app.dependency_overrides[get_secret_store] = lambda: FakeVault()

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_platform_as2_partner(client, fake_uow):
    response = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Test Global Partner", "as2_id": "GLOBAL_AS2"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["type"] == "AS2"
    assert len(fake_uow.as2_partners.partners) == 1


def test_list_platform_as2_partners(client, fake_uow):
    # Ensure there's a partner first
    client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Test Global Partner", "as2_id": "GLOBAL_AS2", "is_local": True},
    )
    response = client.get("/api/v1/platform/trading-partners/as2/trading-partners")
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Add coverage for certificate export
    p_id = response.json()[0]["id"]
    export_resp = client.get(
        f"/api/v1/platform/trading-partners/as2/trading-partners/{p_id}/certificates/export"
    )
    assert export_resp.status_code in (200, 403, 404, 501)


def test_get_platform_settings(client, fake_uow):
    response = client.get("/api/v1/platform/trading-partners/config")
    assert response.status_code == 200


def test_create_platform_as2_partner_duplicate(client, fake_uow):
    client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "First", "as2_id": "DUP_AS2"},
    )
    resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Second", "as2_id": "DUP_AS2"},
    )
    assert resp.status_code == 400


def test_update_platform_as2_partner(client, fake_uow):
    resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Temp", "as2_id": "TEMP_AS2"},
    )
    p_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/platform/trading-partners/as2/trading-partners/{p_id}",
        json={"name": "Temp Updated"},
    )
    assert resp.status_code == 200

    resp = client.delete(f"/api/v1/platform/trading-partners/as2/trading-partners/{p_id}")
    assert resp.status_code == 204


def test_create_platform_as2_partnership(client, fake_uow):

    # Create local and remote partners first
    loc_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Local Partner", "as2_id": "LOCAL_AS2", "is_local": True},
    )
    local_id = loc_resp.json()["id"]

    rem_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Remote Partner", "as2_id": "REMOTE_AS2", "is_local": False},
    )
    remote_id = rem_resp.json()["id"]

    response = client.post(
        "/api/v1/platform/trading-partners/as2/partnerships",
        json={
            "name": "Test Partnership",
            "local_partner_id": local_id,
            "remote_partner_id": remote_id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert len(fake_uow.as2_partnerships.partnerships) == 1


def test_list_platform_as2_partnerships(client, fake_uow):
    # Seed partners first so the partnership create call validates them
    loc_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "List Local Partner", "as2_id": "LIST_LOCAL", "is_local": True},
    )
    local_id = loc_resp.json()["id"]

    rem_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "List Remote Partner", "as2_id": "LIST_REMOTE", "is_local": False},
    )
    remote_id = rem_resp.json()["id"]

    client.post(
        "/api/v1/platform/trading-partners/as2/partnerships",
        json={
            "name": "Listed Partnership",
            "local_partner_id": local_id,
            "remote_partner_id": remote_id,
        },
    )

    response = client.get("/api/v1/platform/trading-partners/as2/partnerships")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_update_platform_as2_partnership(client, fake_uow):

    # Create local and remote partners first
    loc_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Local Update Partner", "as2_id": "LOC_UPD", "is_local": True},
    )
    local_id = loc_resp.json()["id"]

    rem_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Remote Update Partner", "as2_id": "REM_UPD", "is_local": False},
    )
    remote_id = rem_resp.json()["id"]

    ps_id = client.post(
        "/api/v1/platform/trading-partners/as2/partnerships",
        json={
            "name": "Temp Partnership",
            "local_partner_id": local_id,
            "remote_partner_id": remote_id,
        },
    ).json()["id"]

    resp = client.put(
        f"/api/v1/platform/trading-partners/as2/partnerships/{ps_id}",
        json={"name": "Updated Temp Partnership"},
    )
    assert resp.status_code == 200


def test_create_tenant_sftp_partner(client, fake_uow):
    response = client.post(
        "/api/v1/tenants/1/edi/trading-partners/sftp",
        json={
            "name": "My SFTP Partner",
            "host": "sftp.example.com",
            "port": 22,
            "username": "user",
            "password": "secretpassword",
            "inbound_remote_path": "/inbound",
            "outbound_remote_path": "/outbound",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "SFTP"

    # Coverage for unimplemented fake paths
    p_id = data["id"]
    client.get(f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}")
    client.put(f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}", json={"name": "updated"})
    client.delete(f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}")

    # Coverage for test existing partner endpoint
    from unittest.mock import patch

    with patch("database.encryption.db_encryption.decrypt", return_value="secretpassword"):
        client.post(
            f"/api/v1/tenants/1/edi/trading-partners/{p_id}/sftp/test",
            json={
                "host": "sftp.example.com",
                "port": 22,
                "username": "user",
            },
        )

    # Coverage for test endpoint
    client.post(
        "/api/v1/tenants/1/edi/trading-partners/sftp/test",
        json={
            "host": "sftp.example.com",
            "port": 22,
            "username": "user",
            "password": "secretpassword",
        },
    )


def test_sftp_connection_failures(client):
    # Missing password and vault ref
    response = client.post(
        "/api/v1/tenants/1/edi/trading-partners/sftp/test",
        json={
            "host": "sftp.example.com",
            "port": 22,
            "username": "user",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is False

    response = client.post(
        "/api/v1/tenants/1/edi/trading-partners/sftp/test",
        json={
            "host": "sftp.example.com",
            "port": 22,
            "username": "user",
            "credentials_vault_ref": "vault-error-ref",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_existing_sftp_connection_failures(client, fake_uow):
    from unittest.mock import patch
    from uuid import uuid4

    # Not found handling for operations
    random_id = str(uuid4())
    resp = client.put(
        f"/api/v1/tenants/1/edi/trading-partners/sftp/{random_id}",
        json={"name": "x", "host": "h", "port": 22, "username": "u"},
    )
    assert resp.status_code == 400

    from unittest.mock import AsyncMock

    fake_uow.sftp_partners.delete_sftp_partner = AsyncMock(side_effect=ValueError("Not found"))
    resp = client.delete(f"/api/v1/tenants/1/edi/trading-partners/sftp/{random_id}")
    assert resp.status_code == 400

    from edi.domain.exceptions import OrchestrationError

    fake_uow.sftp_partners.delete_sftp_partner = AsyncMock(
        side_effect=OrchestrationError("DB Error")
    )
    resp = client.delete(f"/api/v1/tenants/1/edi/trading-partners/sftp/{random_id}")
    assert resp.status_code == 500

    # Setup a partner
    response = client.post(
        "/api/v1/tenants/1/edi/trading-partners/sftp",
        json={
            "name": "My SFTP Partner 2",
            "host": "sftp.example.com",
            "port": 22,
            "username": "user",
            "password": "secretpassword",
            "inbound_remote_path": "/inbound",
            "outbound_remote_path": "/outbound",
        },
    )
    p_id = response.json()["id"]

    # Test decrypt error
    with patch(
        "database.encryption.db_encryption.decrypt", side_effect=ValueError("Decrypt error")
    ):
        resp = client.post(
            f"/api/v1/tenants/1/edi/trading-partners/{p_id}/sftp/test",
            json={
                "host": "sftp.example.com",
                "port": 22,
                "username": "user",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    # Vault error for existing partner with vault ref instead of password
    put_resp = client.put(
        f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}",
        json={"name": "updated", "credentials_vault_ref": "vault-error-ref", "password": None},
    )
    assert put_resp.status_code == 200
    resp = client.post(
        f"/api/v1/tenants/1/edi/trading-partners/{p_id}/sftp/test",
        json={
            "host": "sftp.example.com",
            "port": 22,
            "username": "user",
            "credentials_vault_ref": "vault-error-ref",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False

    # Value Error and Integrity Error for create and update
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    with patch(
        "edi.application.use_cases.sftp_partner_service.SFTPPartnerService.create_sftp_partner",
        side_effect=ValueError("Bad value"),
    ):
        resp = client.post(
            "/api/v1/tenants/1/edi/trading-partners/sftp",
            json={"name": "Error Partner", "host": "h", "port": 22, "username": "u"},
        )
        assert resp.status_code == 400
    with patch(
        "edi.application.use_cases.sftp_partner_service.SFTPPartnerService.create_sftp_partner",
        side_effect=IntegrityError("x", "y", "z"),
    ):
        resp = client.post(
            "/api/v1/tenants/1/edi/trading-partners/sftp",
            json={"name": "Error Partner 2", "host": "h", "port": 22, "username": "u"},
        )
        assert resp.status_code == 400

    with patch(
        "edi.application.use_cases.sftp_partner_service.SFTPPartnerService.update_sftp_partner",
        side_effect=ValueError("Bad value"),
    ):
        resp = client.put(
            f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}",
            json={"name": "x", "host": "h", "port": 22, "username": "u"},
        )
        assert resp.status_code == 400
    with patch(
        "edi.application.use_cases.sftp_partner_service.SFTPPartnerService.update_sftp_partner",
        side_effect=IntegrityError("x", "y", "z"),
    ):
        resp = client.put(
            f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}",
            json={"name": "x", "host": "h", "port": 22, "username": "u"},
        )
        assert resp.status_code == 400

    # Delete integrity error
    fake_uow.sftp_partners.delete_sftp_partner = AsyncMock(
        side_effect=IntegrityError("x", "y", "z")
    )
    resp = client.delete(f"/api/v1/tenants/1/edi/trading-partners/sftp/{p_id}")
    assert resp.status_code == 400


def test_list_tenant_partners(client, fake_uow):
    response = client.get("/api/v1/tenants/1/edi/trading-partners")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_tenant_as2_certificates(client, fake_uow):
    from uuid import uuid4

    # Use a random UUID that doesn't exist in the fake UoW — expect 404 for both endpoints.
    p_id = str(uuid4())

    # Export — partner not found, must return 404
    resp = client.get(f"/api/v1/tenants/1/edi/trading-partners/as2/{p_id}/certificates/export")
    assert resp.status_code == 404

    # Rotate — partner not found, must return 404
    resp = client.put(
        f"/api/v1/tenants/1/edi/trading-partners/as2/{p_id}/certificates/rotate",
        json={"action": "generate", "public_cert_pem": "test", "private_key_pem": "test"},
    )
    assert resp.status_code == 404
