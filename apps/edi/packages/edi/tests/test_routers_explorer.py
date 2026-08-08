from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from edi.dependencies.auth import get_current_tenant_id, get_current_user_profile
from edi.dependencies.database import get_data_plane_uow, get_global_session
from edi.module import create_edi_app

app = create_edi_app()


def override_get_current_user_profile():
    return {"sub": "test-user", "tenant_id": "1"}


def override_get_current_tenant_id():
    return "1"


@pytest.fixture
def mock_uow():
    """Fresh UoW + repo mock for every test to prevent inter-test pollution."""
    _mock_repo = AsyncMock()
    _mock_repo.explorer_list_edi_messages.return_value = []
    _mock_repo.explorer_list_edi_json.return_value = []

    _mock_uow = AsyncMock()
    _mock_uow.transactions = _mock_repo
    _mock_uow.__aenter__.return_value = _mock_uow
    return _mock_uow


@pytest.fixture(autouse=True)
def setup_dependencies(mock_uow):
    app.dependency_overrides[get_current_user_profile] = override_get_current_user_profile
    app.dependency_overrides[get_current_tenant_id] = override_get_current_tenant_id
    app.dependency_overrides[get_data_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_global_session] = lambda: mock_uow._mock_global
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_explorer_edi_messages(mock_uow):
    response = client.post("/api/v1/tenants/1/edi/explorer/edi-messages", json={"filters": []})
    assert response.status_code == 200
    mock_uow.transactions.explorer_list_edi_messages.assert_called_once_with(
        tenant_id="1", filters=[], limit=50, offset=0
    )


def test_explorer_edi_json(mock_uow):
    response = client.post("/api/v1/tenants/1/edi/explorer/edi-json", json={"filters": []})
    assert response.status_code == 200
    mock_uow.transactions.explorer_list_edi_json.assert_called_once_with(
        tenant_id="1", filters=[], limit=50, offset=0
    )


def test_explorer_rejects_invalid_filter_field(mock_uow):
    response = client.post(
        "/api/v1/tenants/1/edi/explorer/edi-messages",
        json={"filters": [{"field": "tenant_id", "operator": "eq", "value": "1"}]},
    )
    assert response.status_code == 422


def test_explorer_rejects_invalid_operator(mock_uow):
    response = client.post(
        "/api/v1/tenants/1/edi/explorer/edi-messages",
        json={"filters": [{"field": "status", "operator": "like", "value": "DELIVERED"}]},
    )
    assert response.status_code == 422
