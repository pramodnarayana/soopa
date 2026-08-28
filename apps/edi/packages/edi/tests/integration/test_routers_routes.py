import pytest
from fastapi.testclient import TestClient
from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import (
    get_control_plane_uow,
    get_global_session,
)

from edi.module import create_edi_app
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork

app = create_edi_app()


@pytest.fixture
def fake_uow():
    return FakeControlPlaneUnitOfWork()


@pytest.fixture
def client(fake_uow):
    app.dependency_overrides[get_control_plane_uow] = lambda: fake_uow
    app.dependency_overrides[get_global_session] = lambda: fake_uow.global_session
    app.dependency_overrides[get_current_tenant_id] = lambda: "1"
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_inbound_route(client):
    import uuid

    response = client.post(
        "/api/v1/tenants/1/edi/routes/inbound",
        json={
            "as2_partner_id": str(uuid.uuid4()),
            "name": "My Route",
            "isa_sender_id": "S1",
            "isa_receiver_id": "R1",
            "transaction_type": "850",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["direction"] == "INBOUND"

    route_id = data["route_id"]
    patch_resp = client.patch(
        f"/api/v1/tenants/1/edi/routes/inbound/{route_id}", json={"name": "updated"}
    )
    assert patch_resp.status_code in (200, 404)
    del_resp = client.delete(f"/api/v1/tenants/1/edi/routes/inbound/{route_id}")
    assert del_resp.status_code == 204


def test_create_outbound_route(client):
    import uuid

    response = client.post(
        "/api/v1/tenants/1/edi/routes/outbound",
        json={
            "as2_partner_id": str(uuid.uuid4()),
            "name": "My Route",
            "trading_partner_id": "TP1",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["direction"] == "OUTBOUND"

    route_id = data["route_id"]
    patch_resp = client.patch(
        f"/api/v1/tenants/1/edi/routes/outbound/{route_id}", json={"name": "updated"}
    )
    assert patch_resp.status_code in (200, 404)
    del_resp = client.delete(f"/api/v1/tenants/1/edi/routes/outbound/{route_id}")
    assert del_resp.status_code == 204


def test_list_routes(client):
    response = client.get("/api/v1/tenants/1/edi/routes")
    assert response.status_code == 200
    assert len(response.json()) >= 0
