from unittest.mock import AsyncMock, patch

import pytest
from api.dependencies import get_global_session, get_vault
from api.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    app.dependency_overrides[get_global_session] = lambda: AsyncMock()
    app.dependency_overrides[get_vault] = lambda: AsyncMock()
    app.state.db_router = AsyncMock()
    yield TestClient(app)
    app.dependency_overrides.clear()
    if hasattr(app.state, "db_router"):
        delattr(app.state, "db_router")


def test_as2_receive_value_error_generates_negative_mdn(client):
    with patch("api.routers.trading_partners.as2_receive.As2ReceiveService") as mock_service_cls:
        mock_service = AsyncMock()
        mock_service.process_inbound_message.side_effect = ValueError(
            "Test business logic rejection"
        )
        mock_service_cls.return_value = mock_service

        response = client.post(
            "/api/v1/as2/receive",
            headers={"as2-to": "MY-ID", "as2-from": "PARTNER-ID", "message-id": "12345"},
            content=b"some content",
        )

        assert response.status_code == 200
        assert "multipart/report" in response.headers["content-type"]
        assert b"Test business logic rejection" in response.content


def test_as2_receive_generic_exception_generates_negative_mdn(client):
    with patch("api.routers.trading_partners.as2_receive.As2ReceiveService") as mock_service_cls:
        mock_service = AsyncMock()
        mock_service.process_inbound_message.side_effect = Exception("Internal explosion")
        mock_service_cls.return_value = mock_service

        response = client.post(
            "/api/v1/as2/receive",
            headers={"AS2-To": "MY-ID", "AS2-From": "PARTNER-ID", "Message-ID": "12345"},
            content=b"some content",
        )

        assert response.status_code == 200
        assert "multipart/report" in response.headers["content-type"]
        assert b"unexpected-processing-error" in response.content
