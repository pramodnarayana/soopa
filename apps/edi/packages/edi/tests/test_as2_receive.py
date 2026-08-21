from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from unified_api.adapters.inbound.http.dependencies.edi.database import (
    get_control_plane_uow,
    get_data_plane_uow,
    get_global_session,
)
from unified_api.adapters.inbound.http.dependencies.edi.services import get_message_queue

from edi.module import create_edi_app

app = create_edi_app()


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
    app.dependency_overrides[get_control_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_data_plane_uow] = lambda: mock_uow
    app.dependency_overrides[get_global_session] = lambda: mock_uow._mock_global
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
