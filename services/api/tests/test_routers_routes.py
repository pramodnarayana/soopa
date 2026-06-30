import pytest
from api.dependencies import get_tenant_uow
from api.main import app
from api_fakes import FakeUnitOfWork
from fastapi.testclient import TestClient
from identity.dependencies import get_current_tenant_id


@pytest.fixture
def fake_uow():
    return FakeUnitOfWork()


@pytest.fixture
def client(fake_uow):
    app.dependency_overrides[get_tenant_uow] = lambda: fake_uow
    app.dependency_overrides[get_current_tenant_id] = lambda: 1
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_inbound_route(client):
    import uuid

    response = client.post(
        "/api/v1/routes/inbound",
        json={
            "as2_partner_id": str(uuid.uuid4()),
            "isa_sender_id": "S1",
            "isa_receiver_id": "R1",
            "transaction_type": "850",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["direction"] == "INBOUND"


def test_create_outbound_route(client):
    import uuid

    response = client.post(
        "/api/v1/routes/outbound",
        json={
            "as2_partner_id": str(uuid.uuid4()),
            "isa_sender_id": "S1",
            "isa_receiver_id": "R1",
            "transaction_type": "855",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["direction"] == "OUTBOUND"


def test_list_routes(client):
    response = client.get("/api/v1/routes")
    assert response.status_code == 200
    assert len(response.json()) >= 0
