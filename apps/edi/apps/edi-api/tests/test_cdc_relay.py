from typing import Any

import pytest
from api.dependencies.services import get_message_queue
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


def test_cdc_relay_successful_transform_routing(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay correctly routes an outbox TRANSFORM_EVENT insert to TransformQueue."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-123",
        "event_type": "TRANSFORM_EVENT",
        "payload": {"trace_id": "req-123"},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 200

    assert len(memory_queue.sent_messages) == 1
    queue_name, msg_payload = memory_queue.sent_messages[0]
    assert queue_name.value == "TransformOrchestrationQueue"
    assert msg_payload == {
        "idempotency_key": "uuid-123",
        "event_type": "TRANSFORM_EVENT",
        "payload": {"trace_id": "req-123"},
        "tenant_id": 999,
    }


def test_cdc_relay_successful_deliver_routing(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay correctly handles an outbox DELIVER insert event."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-456",
        "event_type": "DELIVER_EVENT",
        "payload": {"trace_id": "req-123", "target": "webhook"},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 200

    assert len(memory_queue.sent_messages) == 1
    queue_name, msg_payload = memory_queue.sent_messages[0]
    assert queue_name == "DeliverQueue"
    assert msg_payload == {
        "idempotency_key": "uuid-456",
        "event_type": "DELIVER_EVENT",
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
    assert response.status_code == 200
    assert len(memory_queue.sent_messages) == 0


def test_cdc_relay_skips_unknown_table(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay skips unknown table sources to prevent silent drops."""
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
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(memory_queue.sent_messages) == 0


def test_cdc_relay_successful_provisioning_routing(memory_queue: InMemoryQueueAdapter) -> None:
    """Tests the CDC relay routes non-data plane events to ProvisioningQueue."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-789",
        "event_type": "AS2_PARTNERSHIP_CREATED",
        "payload": {"tenant_id": 999},
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 200

    assert len(memory_queue.sent_messages) == 1
    queue_name, msg_payload = memory_queue.sent_messages[0]
    assert queue_name == "ProvisioningQueue"
    assert msg_payload == {
        "idempotency_key": "uuid-789",
        "event_type": "AS2_PARTNERSHIP_CREATED",
        "payload": {"tenant_id": 999},
        "tenant_id": 999,
    }


def test_cdc_relay_skips_missing_trace_id(memory_queue: InMemoryQueueAdapter) -> None:
    """Payloads without trace_id must be skipped to prevent poison messages in SQS."""
    payload = {
        "__op": "c",
        "__table": "outbox",
        "idempotency_key": "uuid-no-trace",
        "event_type": "TRANSFORM_EVENT",
        "payload": {},  # Missing trace_id
        "status": "PENDING",
        "tenant_id": 999,
    }

    response = client.post("/internal/cdc/relay", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(memory_queue.sent_messages) == 0
