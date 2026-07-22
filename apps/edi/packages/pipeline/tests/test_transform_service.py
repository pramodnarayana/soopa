import pytest
from domain.direction import MessageDirection
from domain.events import PipelineEventType
from domain.status import MessageStatus
from fakes import FakeTransformerAdapter, InMemoryRepositoryAdapter, InMemoryStorageAdapter
from pipeline.core.transformation import InboundTransformService

pytestmark = pytest.mark.asyncio


async def test_transform_edi_to_json_success() -> None:
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
        "edi_data": "ISA*00*...",
        "format_standard": "X12",
        "transaction_type": "850",
        "status": MessageStatus.RECEIVED,
    }

    # Act
    service = InboundTransformService(transformer, repo)

    await service.transform(trace_id)

    # Assert
    # 1. EDI message status is unchanged by TransformService directly
    assert repo.edi_messages[trace_id]["status"] == MessageStatus.RECEIVED

    # 2. Transformer was called with correct data
    assert len(transformer.transform_edi_calls) == 1
    assert transformer.transform_edi_calls[0]["payload"] == b"ISA*00*..."
    assert transformer.transform_edi_calls[0]["standard"] == "X12"

    # 3. ApiGateway record created in DB
    assert trace_id in repo.api_gateway
    api_payload = repo.api_gateway[trace_id]
    assert api_payload["direction"] == MessageDirection.OUTBOUND
    assert api_payload["status"] == MessageStatus.PENDING_DELIVERY
    assert isinstance(api_payload["payload"], dict)
    assert "metadata" in api_payload["payload"]
    assert api_payload["payload"]["metadata"]["trace_id"] == trace_id
    assert "transactions" in api_payload["payload"]
    assert len(api_payload["payload"]["transactions"]) == 1
    assert api_payload["payload"]["transactions"][0]["transaction_type"] == "850"
    assert api_payload["payload"]["transactions"][0]["fake"] == "json"

    # 5. Outbox event published for TRANSFORM_COMPLETED
    assert len(repo.outbox) == 1
    outbox_event = repo.outbox[0]
    assert outbox_event["event_type"] == PipelineEventType.TRANSFORM_COMPLETED
    assert outbox_event["payload"]["trace_id"] == trace_id
    assert outbox_event["payload"]["direction"] == MessageDirection.INBOUND


async def test_transform_missing_message_raises_error() -> None:
    InMemoryStorageAdapter()
    transformer = FakeTransformerAdapter()
    repo = InMemoryRepositoryAdapter()

    service = InboundTransformService(transformer, repo)

    with pytest.raises(ValueError, match="No EDI message found for trace_id=invalid-trace"):
        await service.transform("invalid-trace")
