from unittest.mock import AsyncMock

import pytest
from api.dependencies import get_current_tenant_id, get_current_user_profile, get_tenant_uow
from api.main import app
from fastapi.testclient import TestClient


def override_get_current_user_profile():
    return {"sub": "test-user", "tenant_id": 1}


def override_get_current_tenant_id():
    return 1


mock_uow = AsyncMock()
mock_repo = AsyncMock()
mock_repo.explorer_list_edi_messages.return_value = []
mock_repo.explorer_list_edi_json.return_value = []
mock_uow.data_plane = mock_repo
mock_uow.__aenter__.return_value = mock_uow


def override_get_tenant_uow():
    return mock_uow


@pytest.fixture(autouse=True)
def setup_dependencies():
    app.dependency_overrides[get_current_user_profile] = override_get_current_user_profile
    app.dependency_overrides[get_current_tenant_id] = override_get_current_tenant_id
    app.dependency_overrides[get_tenant_uow] = override_get_tenant_uow
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_explorer_edi_messages():
    response = client.post("/api/v1/explorer/edi-messages", json={"filters": []})
    assert response.status_code == 200


def test_explorer_edi_json():
    response = client.post("/api/v1/explorer/edi-json", json={"filters": []})
    assert response.status_code == 200
