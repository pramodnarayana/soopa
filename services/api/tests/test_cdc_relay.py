from unittest.mock import AsyncMock, patch

from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_cdc_relay_successful_routing():
    """Tests the CDC relay correctly handles an edi_transformer_outbox insert event."""
    payload = {
        "__op": "c",
        "__table": "edi_transformer_outbox",
        "trace_id": "req-123",
        "s3_uri": "s3://edi-bucket/raw.x12",
    }

    with patch("api.cdc_relay.queue_service.send", new_callable=AsyncMock) as mock_send:
        # Should return 202 Accepted and log internally
        response = client.post("/internal/cdc/relay", json=payload)
        assert response.status_code == 202

        # Verify SQS send was called correctly
        mock_send.assert_called_once_with(
            queue_name="EdiTransformerQueue",
            payload={"trace_id": "req-123", "s3_uri": "s3://edi-bucket/raw.x12"},
        )


def test_cdc_relay_ignores_updates_and_deletes():
    """Tests that updates/deletes to append-only outboxes are safely ignored."""
    payload = {
        "__op": "u",
        "__table": "edi_transformer_outbox",
        "trace_id": "req-123",
        "s3_uri": "s3://edi-bucket/raw.x12",
    }

    # Should return 200/202 instantly without processing
    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 202


def test_cdc_relay_rejects_unknown_table():
    """Tests the CDC relay fails explicitly on unknown table sources to prevent silent drops."""
    payload = {
        "__op": "c",
        "__table": "unknown_table",
        "trace_id": "req-123",
        "s3_uri": "s3://edi-bucket/raw.x12",
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown table source"
