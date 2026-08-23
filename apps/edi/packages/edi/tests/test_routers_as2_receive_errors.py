from unittest.mock import AsyncMock

import pytest
from edi.adapters.outbound.database.session import get_global_session
from fastapi.testclient import TestClient
from unified_api.adapters.inbound.http.dependencies.edi.services import (
    get_as2_receiver_service,
    get_secret_store,
)

from edi.domain.exceptions import OrchestrationError
from edi.module import create_edi_app

app = create_edi_app()


@pytest.fixture
def client():
    app.dependency_overrides[get_global_session] = lambda: AsyncMock()
    app.dependency_overrides[get_secret_store] = lambda: AsyncMock()
    app.state.db_router = AsyncMock()
    yield TestClient(app)
    app.dependency_overrides.clear()
    if hasattr(app.state, "db_router"):
        delattr(app.state, "db_router")


def test_as2_receive_value_error_generates_negative_mdn(client):
    mock_service = AsyncMock()
    mock_service.process_inbound_message.side_effect = ValueError("Test business logic rejection")
    app.dependency_overrides[get_as2_receiver_service] = lambda: mock_service

    response = client.post(
        "/api/v1/as2/receive",
        headers={"as2-to": "MY-ID", "as2-from": "PARTNER-ID", "message-id": "12345"},
        content=b"some content",
    )

    assert response.status_code == 200
    assert "multipart/report" in response.headers["content-type"]
    assert b"unexpected-processing-error" in response.content


def test_as2_receive_generic_exception_generates_negative_mdn(client):
    mock_service = AsyncMock()
    mock_service.process_inbound_message.side_effect = OrchestrationError("Internal explosion")
    app.dependency_overrides[get_as2_receiver_service] = lambda: mock_service

    response = client.post(
        "/api/v1/as2/receive",
        headers={"AS2-To": "MY-ID", "AS2-From": "PARTNER-ID", "Message-ID": "12345"},
        content=b"some content",
    )

    assert response.status_code == 200
    assert "multipart/report" in response.headers["content-type"]
    assert b"unexpected-processing-error" in response.content
