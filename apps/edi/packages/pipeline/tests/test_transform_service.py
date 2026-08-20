"""
Unit tests for InboundTransformUseCase — verifies inbound EDI→JSON transformation.
All test doubles are imported from fakes.py (DRY). No mock library used.
"""

import pytest
from domain.direction import MessageDirection
from domain.events import PipelineEventType
from domain.status import MessageStatus
from fakes import FakeDataPlaneUnitOfWork, FakeTransformerAdapter


class FakeSettings:
    edi_aws_bucket_name = "test-bucket"
    enable_heavy_compute_queue = False


from pipeline.application.inbound_transform_use_case import InboundTransformUseCase

pytestmark = pytest.mark.asyncio


async def test_transform_edi_to_json_success() -> None:
    # Arrange
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()

    trace_id = "trace-123"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "edi_data": "ISA*00*...",
        "format_standard": "X12",
        "transaction_type": "850",
        "status": MessageStatus.RECEIVED,
    }

    # Act
    settings = FakeSettings()
    use_case = InboundTransformUseCase(uow=uow, transformer=transformer, settings=settings)
    await use_case.execute(trace_id)

    # Assert — transformer was called with correct data
    assert len(transformer.transform_edi_calls) == 1
    assert transformer.transform_edi_calls[0]["payload"] == b"ISA*00*..."
    assert transformer.transform_edi_calls[0]["standard"] == "X12"

    # ApiGateway record created
    assert trace_id in uow.repository.api_gateway
    api_payload = uow.repository.api_gateway[trace_id]
    assert api_payload["direction"] == MessageDirection.OUTBOUND
    assert api_payload["status"] == MessageStatus.PENDING_DELIVERY
    assert isinstance(api_payload["payload"], dict)
    assert "metadata" in api_payload["payload"]
    assert api_payload["payload"]["metadata"]["trace_id"] == trace_id
    assert "transactions" in api_payload["payload"]
    assert len(api_payload["payload"]["transactions"]) == 1
    assert api_payload["payload"]["transactions"][0]["transaction_type"] == "850"
    assert api_payload["payload"]["transactions"][0]["fake"] == "json"

    # Outbox event published for TRANSFORM_COMPLETED
    assert len(uow.outbox.events) == 1
    outbox_event = uow.outbox.events[0]
    assert outbox_event["event_type"] == PipelineEventType.TRANSFORM_COMPLETED
    assert outbox_event["payload"]["trace_id"] == trace_id
    assert outbox_event["payload"]["direction"] == MessageDirection.INBOUND

    # UoW was committed
    assert uow.committed


async def test_transform_missing_message_raises_error() -> None:
    uow = FakeDataPlaneUnitOfWork()
    transformer = FakeTransformerAdapter()

    settings = FakeSettings()
    use_case = InboundTransformUseCase(uow=uow, transformer=transformer, settings=settings)

    with pytest.raises(ValueError, match="No EDI message found for trace_id=invalid-trace"):
        await use_case.execute("invalid-trace")
