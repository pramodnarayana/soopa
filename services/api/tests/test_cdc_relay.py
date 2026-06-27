from typing import Any

import pytest
from api.dependencies import get_message_queue
from api.main import app
from api.ports.message_queue import MessageQueuePort
from fastapi.testclient import TestClient


class InMemoryQueueAdapter(MessageQueuePort):
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, dict[str, Any]]] = []

    async def send(self, queue_name: str, payload: dict[str, Any]) -> None:
        self.sent_messages.append((queue_name, payload))


@pytest.fixture
def memory_queue() -> InMemoryQueueAdapter:  # type: ignore[misc]
    queue = InMemoryQueueAdapter()
    app.dependency_overrides[get_message_queue] = lambda: queue
    yield queue
    app.dependency_overrides.pop(get_message_queue, None)


client = TestClient(app)


def test_cdc_relay_successful_translate_routing(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay correctly handles an outbox TRANSLATE insert event."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-123",
        "event_type": "TRANSLATE",
        "payload": {"trace_id": "req-123"},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 202

    assert len(memory_queue.sent_messages) == 1
    queue_name, msg_payload = memory_queue.sent_messages[0]
    assert queue_name == "TranslateQueue"
    assert msg_payload == {
        "idempotency_key": "uuid-123",
        "event_type": "TRANSLATE",
        "payload": {"trace_id": "req-123"},
        "tenant_id": 999,
    }


def test_cdc_relay_successful_deliver_routing(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay correctly handles an outbox DELIVER insert event."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-456",
        "event_type": "DELIVER",
        "payload": {"trace_id": "req-123", "target": "webhook"},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 202

    assert len(memory_queue.sent_messages) == 1
    queue_name, msg_payload = memory_queue.sent_messages[0]
    assert queue_name == "DeliverQueue"
    assert msg_payload == {
        "idempotency_key": "uuid-456",
        "event_type": "DELIVER",
        "payload": {"trace_id": "req-123", "target": "webhook"},
        "tenant_id": 999,
    }


def test_cdc_relay_ignores_updates_and_deletes(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests that updates/deletes to append-only outboxes are safely ignored."""
    payload = {
        "__op": "u",
        "__table": "outbox",
        "idempotency_key": "uuid-123",
        "event_type": "TRANSLATE",
        "payload": {},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 202
    assert len(memory_queue.sent_messages) == 0


def test_cdc_relay_rejects_unknown_table(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay fails explicitly on unknown table sources to prevent silent drops."""
    payload = {
        "__op": "c",
        "__table": "unknown_table",
        "idempotency_key": "uuid-123",
        "event_type": "TRANSLATE",
        "payload": {},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown table source"
    assert len(memory_queue.sent_messages) == 0


def test_cdc_relay_rejects_unknown_event_type(memory_queue: InMemoryQueueAdapter) -> None:
    """Unknown event types must fail-fast so they are not silently dropped."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-789",
        "event_type": "MYSTERY_EVENT",
        "payload": {"trace_id": "req-123"},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 400
    assert "MYSTERY_EVENT" in response.json()["detail"]
    assert len(memory_queue.sent_messages) == 0


def test_cdc_relay_rejects_missing_trace_id(memory_queue: InMemoryQueueAdapter) -> None:
    """Payloads without trace_id must be rejected to prevent poison messages in SQS."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-no-trace",
        "event_type": "TRANSLATE",
        "payload": {},  # Missing trace_id
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 400
    assert "trace_id" in response.json()["detail"]
    assert len(memory_queue.sent_messages) == 0
