from api.dependencies import get_tenant_uow, get_uow, require_platform_admin
from api.main import app
from api_fakes import FakeUnitOfWork
from fastapi.testclient import TestClient
from identity.dependencies import get_current_tenant_id

fake_uow = FakeUnitOfWork()

app.dependency_overrides[get_uow] = lambda: fake_uow
app.dependency_overrides[get_tenant_uow] = lambda: fake_uow
app.dependency_overrides[get_current_tenant_id] = lambda: 1
app.dependency_overrides[require_platform_admin] = lambda: 0

client = TestClient(app)


def test_create_platform_as2_partner():
    response = client.post(
        "/api/v1/platform/partners/as2/trading-partners",
        json={"name": "Test Global Partner", "as2_id": "GLOBAL_AS2"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["type"] == "AS2"
    assert len(fake_uow.control_plane.partners) == 1


def test_list_platform_as2_partners():
    response = client.get("/api/v1/platform/partners/as2/trading-partners")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_create_platform_as2_partnership():
    import uuid

    local_id = str(uuid.uuid4())
    remote_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/platform/partners/as2/partnerships",
        json={"local_partner_id": local_id, "remote_partner_id": remote_id},
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert len(fake_uow.control_plane.partnerships) == 1


def test_list_platform_as2_partnerships():
    response = client.get("/api/v1/platform/partners/as2/partnerships")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_create_tenant_sftp_partner():
    response = client.post(
        "/api/v1/partners/sftp",
        json={
            "name": "My SFTP",
            "host": "sftp.test",
            "username": "user",
            "credentials_vault_ref": "ref",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "SFTP"


def test_create_tenant_webhook_partner():
    response = client.post(
        "/api/v1/partners/webhook", json={"name": "My Webhook", "url": "http://hook.test"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "WEBHOOK"
