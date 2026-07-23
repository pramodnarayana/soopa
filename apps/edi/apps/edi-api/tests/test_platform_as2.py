from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from api.dependencies.auth import (
    get_current_tenant_id,
    get_current_user_profile,
    get_raw_jwt,
    require_platform_admin,
)
from api.dependencies.database import get_tenant_uow, get_uow
from api.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.transactions = AsyncMock()

    # Mock for list_platform_as2_partnerships
    mock_result = Mock()
    mock_scalars = Mock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    uow.global_session.execute.return_value = mock_result

    return uow


@pytest.fixture
def client(mock_uow):
    app.dependency_overrides[get_current_tenant_id] = lambda: 1
    app.dependency_overrides[get_uow] = lambda: mock_uow
    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    app.dependency_overrides[get_raw_jwt] = lambda: {"sub": "test"}
    app.dependency_overrides[require_platform_admin] = lambda: True
    app.dependency_overrides[get_current_user_profile] = lambda: {
        "permissions": ["certificates:export_private", "certificates:rotate"]
    }

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_list_as2_partnerships(client, mock_uow):
    client.get("/api/v1/platform/trading-partners/as2/partnerships")


def test_create_as2_partnership(client, mock_uow):
    client.post(
        "/api/v1/platform/trading-partners/as2/partnerships",
        json={
            "trading_partner_id": "tp1",
            "local_partner_id": str(uuid4()),
            "remote_partner_id": str(uuid4()),
        },
    )


def test_update_as2_partnership(client, mock_uow):
    pid = uuid4()
    mock_uow.as2_partnerships.get_as2_partnership.return_value = {"id": str(pid)}
    client.put(
        f"/api/v1/platform/trading-partners/as2/partnerships/{pid}",
        json={"trading_partner_id": "tp1"},
    )


def test_delete_as2_partnership(client, mock_uow):
    pid = uuid4()
    client.delete(f"/api/v1/platform/trading-partners/as2/partnerships/{pid}")
