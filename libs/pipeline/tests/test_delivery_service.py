import pytest
from fakes import InMemoryRepositoryAdapter, InMemoryStorageAdapter
from pipeline.core.deliver import DeliveryService

pytestmark = pytest.mark.asyncio


class FakeHttpDeliveryAdapter:
    def __init__(self, status_code: int = 200) -> None:
        self.delivered: list[dict] = []
        self.status_code = status_code

    async def deliver(self, url: str, payload: bytes) -> int:
        self.delivered.append({"url": url, "payload": payload})
        return self.status_code


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


async def test_delivery_service_http_failure_sets_failed_status() -> None:
    """Non-2xx HTTP responses should set payload to FAILED and raise."""
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter(status_code=503)

    trace_id = "trace-fail"
    s3_uri = "s3://fake-bucket/api_payloads/trace-fail/translated.json"

    storage.store[s3_uri] = b'{"hello": "world"}'
    repo.api_payloads[trace_id] = {
        "trace_id": trace_id,
        "s3_key": s3_uri,
        "status": "PENDING_DELIVERY",
    }

    service = DeliveryService(storage, repo, http_adapter)
    with pytest.raises(RuntimeError, match="Delivery failed with HTTP status 503"):
        await service.deliver(trace_id, target_url="https://webhook.example.com/edi")

    # Status must be FAILED, not PENDING_DELIVERY
    assert repo.api_payloads[trace_id]["status"] == "FAILED"
    # Delivery was attempted (HTTP call was made)
    assert len(http_adapter.delivered) == 1


async def test_delivery_service_exception_sets_failed_status() -> None:
    """Exceptions from storage/HTTP should set payload to FAILED and propagate."""

    class BrokenStorageAdapter(InMemoryStorageAdapter):
        async def download(self, uri: str) -> bytes:
            raise ConnectionError("S3 connection failed")

    storage = BrokenStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter()

    trace_id = "trace-exc"
    repo.api_payloads[trace_id] = {
        "trace_id": trace_id,
        "s3_key": "s3://fake-bucket/missing",
        "status": "PENDING_DELIVERY",
    }

    service = DeliveryService(storage, repo, http_adapter)
    with pytest.raises(RuntimeError, match="Delivery failed due to exception"):
        await service.deliver(trace_id, target_url="https://webhook.example.com/edi")

    assert repo.api_payloads[trace_id]["status"] == "FAILED"
    assert len(http_adapter.delivered) == 0
