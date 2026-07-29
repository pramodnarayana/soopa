from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.dependencies.auth import get_current_tenant_id
from api.dependencies.database import get_control_plane_uow, get_data_plane_uow, get_global_session
from api.main import app


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.__aenter__.return_value = uow
    uow.transactions = AsyncMock()
    uow.webhooks = AsyncMock()
    return uow


@pytest.fixture
def client(mock_uow):
    app.dependency_overrides[get_current_tenant_id] = lambda: "1"
    app.dependency_overrides[get_control_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_data_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_global_session] = lambda: mock_uow._mock_global

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_list_webhooks(client, mock_uow):
    mock_uow.webhooks.list_webhooks.return_value = []
    response = client.get("/api/v1/webhooks")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    mock_uow.webhooks.list_webhooks.assert_called_once_with("1")
