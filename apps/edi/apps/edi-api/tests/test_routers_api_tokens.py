from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies.auth import get_current_tenant_id
from api.dependencies.services import get_api_token_repo
from api.routers.developers.api_tokens import router

app = FastAPI()
app.include_router(router)


def override_get_tenant_id():
    return "tenant_1"


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def client(mock_repo):
    app.dependency_overrides[get_current_tenant_id] = override_get_tenant_id
    app.dependency_overrides[get_api_token_repo] = lambda: mock_repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_api_tokens(client, mock_repo):
    mock_repo.list_api_tokens.return_value = [
        {
            "id": str(uuid4()),
            "name": "Test Token",
            "client_id": "client_1",
            "active": True,
            "created_at": "2023-01-01T00:00:00Z",
            "last_used_at": None,
            "expires_at": None,
        }
    ]

    response = client.get("/api/v1/developers/tokens")

    assert response.status_code == 200
    data = response.json()
    assert len(data["tokens"]) == 1
    assert data["tokens"][0]["name"] == "Test Token"
    mock_repo.list_api_tokens.assert_called_once_with("tenant_1")
    assert isinstance(mock_repo.list_api_tokens.call_args[0][0], str)

