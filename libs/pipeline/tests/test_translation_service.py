import pytest
from fakes import FakeTransformerAdapter, InMemoryRepositoryAdapter, InMemoryStorageAdapter
from pipeline.core.translate import TranslationService

pytestmark = pytest.mark.asyncio


async def test_translate_edi_to_json_success() -> None:
    # Arrange
    storage = InMemoryStorageAdapter()
    transformer = FakeTransformerAdapter()
    repo = InMemoryRepositoryAdapter()

    # Pre-seed storage and repo with an incoming EDI payload
    trace_id = "trace-123"
    s3_uri = "s3://edi-inbound/raw.x12"
    storage.store[s3_uri] = b"ISA*00*..."

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "edi_data": s3_uri,
        "format_standard": "X12",
        "transaction_type": "850",
        "status": "RECEIVED",
    }

    # Act
    service = TranslationService(storage, transformer, repo)
    await service.translate(trace_id)

    # Assert
    # 1. EDI message status updated to TRANSLATED
    assert repo.edi_messages[trace_id]["status"] == "TRANSLATED"

    # 2. Transformer was called with correct data
    assert len(transformer.translate_edi_calls) == 1
    assert transformer.translate_edi_calls[0]["payload"] == b"ISA*00*..."
    assert transformer.translate_edi_calls[0]["standard"] == "X12"

    # 3. JSON payload uploaded to storage
    assert storage.upload_count == 1

    # 4. ApiGateway record created in DB
    assert trace_id in repo.api_gateway
    api_payload = repo.api_gateway[trace_id]
    assert api_payload["direction"] == "OUTBOUND"
    assert api_payload["status"] == "PENDING_DELIVERY"
    assert api_payload["request"].startswith("s3://fake-bucket")

    # 5. Outbox event published for DELIVER
    assert len(repo.outbox) == 1
    outbox_event = repo.outbox[0]
    assert outbox_event["event_type"] == "DELIVER"
    assert outbox_event["payload"]["trace_id"] == trace_id


async def test_translate_missing_message_raises_error() -> None:
    storage = InMemoryStorageAdapter()
    transformer = FakeTransformerAdapter()
    repo = InMemoryRepositoryAdapter()

    service = TranslationService(storage, transformer, repo)

    with pytest.raises(ValueError, match="No EDI message found for trace_id=invalid-trace"):
        await service.translate("invalid-trace")
