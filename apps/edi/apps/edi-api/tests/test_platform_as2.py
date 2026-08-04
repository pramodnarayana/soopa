from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from identity.domain.identity_context import PLATFORM_TENANT_ID

from api.dependencies.auth import (
    get_current_tenant_id,
    get_current_user_profile,
    get_raw_jwt,
    require_platform_admin,
)
from api.dependencies.database import get_control_plane_uow, get_data_plane_uow, get_global_session
from api.main import app


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
    app.dependency_overrides[get_current_tenant_id] = lambda: PLATFORM_TENANT_ID
    app.dependency_overrides[get_control_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_data_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_global_session] = lambda: mock_uow._mock_global
    app.dependency_overrides[get_raw_jwt] = lambda: {"sub": "test"}
    app.dependency_overrides[require_platform_admin] = lambda: PLATFORM_TENANT_ID
    app.dependency_overrides[get_current_user_profile] = lambda: {
        "permissions": ["certificates:export_private", "certificates:rotate"]
    }
    from api.dependencies.services import get_vault

    app.dependency_overrides[get_vault] = lambda: AsyncMock()

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
    pid = str(uuid4())
    mock_uow.as2_partnerships.get_as2_partnership.return_value = {"id": str(pid)}
    client.put(
        f"/api/v1/platform/trading-partners/as2/partnerships/{pid}",
        json={"trading_partner_id": "tp1"},
    )


def test_delete_as2_partnership(client, mock_uow):
    pid = str(uuid4())
    client.delete(f"/api/v1/platform/trading-partners/as2/partnerships/{pid}")


def test_create_as2_partner_unauthorized():
    # Test unauthenticated
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as local_client:
        response = local_client.post(
            "/api/v1/platform/trading-partners/as2/trading-partners",
            json={"name": "Test", "as2_id": "TEST_ID", "is_local": True},
        )
        assert response.status_code == 401


def test_create_as2_partner_forbidden(client):
    # Test authenticated but without platform admin
    from fastapi import HTTPException

    from api.dependencies.auth import get_platform_user_profile

    def mock_forbidden():
        raise HTTPException(status_code=403, detail="Forbidden")

    app.dependency_overrides[get_platform_user_profile] = mock_forbidden

    response = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={"name": "Test", "as2_id": "TEST_ID", "is_local": True},
    )
    assert response.status_code == 403
