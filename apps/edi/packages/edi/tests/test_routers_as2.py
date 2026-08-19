from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from edi.dependencies.auth import get_current_tenant_id, get_current_user_profile, get_raw_jwt
from edi.dependencies.database import get_control_plane_uow, get_data_plane_uow, get_global_session
from edi.dependencies.services import get_secret_store
from edi.module import create_edi_app

app = create_edi_app()


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.transactions = AsyncMock()
    return uow


@pytest.fixture
def mock_vault():
    vault = AsyncMock()
    vault.retrieve_private_key.return_value = b"test_private_key"
    vault.store_private_key.return_value = "vault_ref"
    return vault


@pytest.fixture
def client(mock_uow, mock_vault):
    app.dependency_overrides[get_current_tenant_id] = lambda: "1"
    app.dependency_overrides[get_control_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_data_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_global_session] = lambda: mock_uow._mock_global
    app.dependency_overrides[get_raw_jwt] = lambda: {"sub": "test"}
    app.dependency_overrides[get_current_user_profile] = lambda: {
        "permissions": ["certificates:export_private", "certificates:rotate"]
    }
    app.dependency_overrides[get_secret_store] = lambda: mock_vault

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_export_as2_certificates(client, mock_uow):
    pid = str(uuid4())

    mock_partner = mock_uow.as2_partners.get_as2_partner.return_value
    mock_partner.public_cert_pem = "cert_pem"
    mock_partner.prev_public_cert_pem = "prev_cert_pem"
    mock_partner.is_local = True
    mock_partner.private_key_vault_ref = "ref1"
    mock_partner.prev_private_key_vault_ref = "ref2"

    response = client.get(f"/api/v1/trading-partners/as2/{pid}/certificates/export")
    assert response.status_code in (200, 403, 404)


def test_rotate_as2_certificates(client, mock_uow):
    pid = str(uuid4())

    mock_partner = mock_uow.as2_partners.get_as2_partner.return_value
    mock_partner.public_cert_pem = "cert_pem"
    mock_partner.prev_public_cert_pem = "prev_cert_pem"
    mock_partner.is_local = True
    mock_partner.private_key_vault_ref = "ref1"
    mock_partner.prev_private_key_vault_ref = "ref2"
    mock_partner.as2_id = "test_id"
    mock_partner.name = "test_name"
    mock_partner.url = "http://localhost"

    client.put(
        f"/api/v1/trading-partners/as2/{pid}/certificates/rotate", json={"action": "generate"}
    )


def test_list_edi_headers(client, mock_uow):
    mock_uow.transactions.get_edi_headers.return_value = []
    client.get("/api/v1/tenants/1/edi/edi-headers")


def test_create_edi_header(client, mock_uow):
    client.post("/api/v1/tenants/1/edi/edi-headers", json={"trading_partner_id": "tp1"})


def test_update_edi_header(client, mock_uow):
    hid = str(uuid4())
    mock_uow.transactions.get_edi_header.return_value = {"id": str(hid)}
    client.patch(f"/api/v1/tenants/1/edi/edi-headers/{hid}", json={"status": "PROCESSING"})


def test_delete_edi_header(client, mock_uow):
    hid = str(uuid4())
    client.delete(f"/api/v1/tenants/1/edi/edi-headers/{hid}")


def test_list_as2_partnerships(client, mock_uow):
    mock_uow.as2_partnerships.get_as2_partnerships.return_value = []
    client.get("/api/v1/trading-partners/as2/partnerships")


def test_create_as2_partnership(client, mock_uow):
    client.post(
        "/api/v1/trading-partners/as2/partnerships",
        json={
            "trading_partner_id": "tp1",
            "local_partner_id": str(uuid4()),
            "remote_partner_id": str(uuid4()),
        },
    )


def test_update_as2_partnership(client, mock_uow):
    pid = str(uuid4())
    mock_uow.as2_partnerships.get_as2_partnership.return_value = {"id": str(pid)}
    client.put(
        f"/api/v1/trading-partners/as2/partnerships/{pid}", json={"trading_partner_id": "tp1"}
    )


def test_delete_as2_partnership(client, mock_uow):
    pid = str(uuid4())
    client.delete(f"/api/v1/trading-partners/as2/partnerships/{pid}")


def test_list_as2_partners(client, mock_uow):
    mock_uow.as2_partners.list_as2_partners.return_value = []
    client.get("/api/v1/trading-partners/as2/trading-partners")


def test_create_as2_partner(client, mock_uow):
    client.post(
        "/api/v1/trading-partners/as2/trading-partners",
        json={
            "name": "partner1",
            "as2_id": "tp1",
            "is_local": True,
            "public_cert_pem": "cert_pem",
            "url": "http://localhost:8000/as2",
        },
    )


def test_update_as2_partner(client, mock_uow):
    pid = str(uuid4())
    mock_partner = mock_uow.as2_partners.get_as2_partner.return_value
    mock_partner.id = pid
    client.put(
        f"/api/v1/trading-partners/as2/trading-partners/{pid}", json={"name": "partner1_updated"}
    )


def test_delete_as2_partner(client, mock_uow):
    pid = str(uuid4())
    client.delete(f"/api/v1/trading-partners/as2/trading-partners/{pid}")
