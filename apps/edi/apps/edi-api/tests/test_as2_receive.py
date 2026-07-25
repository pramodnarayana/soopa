from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.dependencies.database import get_tenant_uow, get_uow
from api.dependencies.services import get_message_queue
from api.main import app


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.transactions = AsyncMock()
    return uow


@pytest.fixture
def mock_mq():
    mq = AsyncMock()
    return mq


@pytest.fixture
def client(mock_uow, mock_mq):
    app.dependency_overrides[get_uow] = lambda: mock_uow
    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    app.dependency_overrides[get_message_queue] = lambda: mock_mq

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_as2_receive(client, mock_uow, mock_mq):
    mock_uow.inbound_routes.get_inbound_routes.return_value = []
    client.post(
        "/api/v1/trading-partners/as2/receive/tp1",
        headers={"as2-to": "receiver", "as2-from": "sender", "message-id": "1234"},
        content=b"test",
    )

    client.post("/api/v1/trading-partners/as2/receive/tp2", headers={}, content=b"test")
