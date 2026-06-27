import pytest
from fakes import InMemoryRepositoryAdapter, InMemoryStorageAdapter
from pipeline.core.deliver import DeliveryService

pytestmark = pytest.mark.asyncio


class FakeHttpDeliveryAdapter:
    def __init__(self) -> None:
        self.delivered: list[dict] = []

    async def deliver(self, url: str, payload: bytes) -> int:
        self.delivered.append({"url": url, "payload": payload})
        return 200


async def test_delivery_service_json_webhook() -> None:
    # Arrange
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter()

    trace_id = "trace-456"
    s3_uri = "s3://fake-bucket/api_payloads/trace-456/translated.json"

    # Pre-seed the DB and Storage
    storage.store[s3_uri] = b'{"hello": "world"}'
    repo.api_payloads[trace_id] = {
        "trace_id": trace_id,
        "s3_key": s3_uri,
        "status": "PENDING_DELIVERY",
    }

    # Act
    service = DeliveryService(storage, repo, http_adapter)
    await service.deliver(trace_id, target_url="https://webhook.example.com/edi")

    # Assert
    # 1. Payload delivered over HTTP
    assert len(http_adapter.delivered) == 1
    assert http_adapter.delivered[0]["url"] == "https://webhook.example.com/edi"
    assert http_adapter.delivered[0]["payload"] == b'{"hello": "world"}'

    # 2. Database status updated to DELIVERED
    assert repo.api_payloads[trace_id]["status"] == "DELIVERED"
