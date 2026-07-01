import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from database.models import ApiGateway, EdiMessage
from pipeline.adapters.repository import SqlAlchemyRepositoryAdapter

pytestmark = pytest.mark.asyncio


async def test_get_edi_message_success() -> None:
    mock_session = AsyncMock()
    mock_result = MagicMock()

    mock_record = MagicMock(spec=EdiMessage)
    mock_record.trace_id = uuid.uuid4()
    mock_record.edi_data = "s3://foo"
    mock_record.format_standard = "X12"
    mock_record.transaction_type = "850"
    mock_record.status = "RECEIVED"

    mock_result.scalar_one_or_none.return_value = mock_record
    mock_session.execute.return_value = mock_result

    adapter = SqlAlchemyRepositoryAdapter(mock_session)
    result = await adapter.get_edi_message(str(mock_record.trace_id))

    assert result is not None
    assert result["edi_data"] == "s3://foo"
    assert result["format_standard"] == "X12"
    assert result["status"] == "RECEIVED"


async def test_update_edi_message_status() -> None:
    mock_session = AsyncMock()
    adapter = SqlAlchemyRepositoryAdapter(mock_session)

    trace_id = str(uuid.uuid4())
    await adapter.update_edi_message_status(trace_id, "TRANSLATED")

    mock_session.execute.assert_awaited_once()
    mock_session.flush.assert_awaited_once()


async def test_save_api_payload() -> None:
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    adapter = SqlAlchemyRepositoryAdapter(mock_session)

    trace_id = str(uuid.uuid4())
    await adapter.save_api_payload(trace_id, "OUTBOUND", "s3://out", "PENDING_DELIVERY")

    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, ApiGateway)
    assert str(added_obj.trace_id) == trace_id
    assert added_obj.request == "s3://out"

    mock_session.flush.assert_awaited_once()


async def test_publish_outbox_event() -> None:
    mock_session = AsyncMock()
    adapter = SqlAlchemyRepositoryAdapter(mock_session)

    idempotency_key = str(uuid.uuid4())
    await adapter.publish_outbox_event(idempotency_key, "DELIVER", {"trace_id": "123"})

    mock_session.execute.assert_awaited_once()
    mock_session.flush.assert_awaited_once()


async def test_get_api_payload() -> None:
    mock_session = AsyncMock()
    mock_result = MagicMock()

    mock_record = MagicMock(spec=ApiGateway)
    mock_record.trace_id = uuid.uuid4()
    mock_record.request = "s3://out"
    mock_record.status = "PENDING_DELIVERY"

    mock_result.scalar_one_or_none.return_value = mock_record
    mock_session.execute.return_value = mock_result

    adapter = SqlAlchemyRepositoryAdapter(mock_session)
    result = await adapter.get_api_payload(str(mock_record.trace_id))

    assert result is not None
    assert result["status"] == "PENDING_DELIVERY"
    assert result["request"] == "s3://out"


async def test_update_api_payload_status() -> None:
    mock_session = AsyncMock()
    adapter = SqlAlchemyRepositoryAdapter(mock_session)

    trace_id = str(uuid.uuid4())
    await adapter.update_api_payload_status(trace_id, "DELIVERED")

    mock_session.execute.assert_awaited_once()
    mock_session.flush.assert_awaited_once()
