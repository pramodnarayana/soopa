from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from api.dependencies import get_api_token_repo
from api.routers.developers.api_tokens import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.dependencies import get_current_tenant_id

app = FastAPI()
app.include_router(router)


def override_get_tenant_id():
    return 1


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def client(mock_repo):
    app.dependency_overrides[get_current_tenant_id] = override_get_tenant_id
    app.dependency_overrides[get_api_token_repo] = lambda: mock_repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_api_token(client, mock_repo):
    token_id = uuid4()
    mock_repo.create_api_token.return_value = token_id

    response = client.post("/api/v1/developers/tokens", json={"name": "Test Token"})

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == str(token_id)
    assert data["name"] == "Test Token"
    assert "client_id" in data
    assert "client_secret" in data
    assert data["active"] is False


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


def test_revoke_api_token(client, mock_repo):
    mock_repo.update_api_token.return_value = True
    t_id = uuid4()

    response = client.patch(f"/api/v1/developers/tokens/{t_id}", json={"active": False})
    assert response.status_code == 204


def test_revoke_api_token_not_found(client, mock_repo):
    mock_repo.update_api_token.return_value = False
    t_id = uuid4()

    response = client.patch(f"/api/v1/developers/tokens/{t_id}", json={"active": False})
    assert response.status_code == 404


def test_delete_api_token(client, mock_repo):
    mock_repo.delete_api_token.return_value = True
    t_id = uuid4()

    response = client.delete(f"/api/v1/developers/tokens/{t_id}")
    assert response.status_code == 204


def test_delete_api_token_not_found(client, mock_repo):
    mock_repo.delete_api_token.return_value = False
    t_id = uuid4()

    response = client.delete(f"/api/v1/developers/tokens/{t_id}")
    assert response.status_code == 404
