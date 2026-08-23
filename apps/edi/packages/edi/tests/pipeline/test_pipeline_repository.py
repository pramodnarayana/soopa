import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from edi.adapters.outbound.database.models.data_plane import ApiGateway
from edi.adapters.outbound.pipeline.repository import SqlAlchemyRepositoryAdapter
from edi.config.settings import AppSettings
from edi.domain.direction import MessageDirection
from edi.domain.status import MessageStatus
from tests.pipeline.fakes import InMemoryStorageAdapter

pytestmark = pytest.mark.asyncio


def make_adapter(session):
    settings = AppSettings()
    settings.storage_backend = "local"
    storage = InMemoryStorageAdapter()
    return SqlAlchemyRepositoryAdapter(session, settings, storage)


async def test_get_edi_message_success() -> None:
    mock_session = AsyncMock()
    mock_result = MagicMock()

    from datetime import UTC, datetime

    from edi.adapters.outbound.database.models.data_plane import EdiMessage

    mock_record = EdiMessage()
    mock_record.id = str(uuid.uuid4())
    mock_record.tenant_id = "1"
    mock_record.trace_id = str(uuid.uuid4())
    mock_record.edi_data = "s3://foo"
    mock_record.direction = MessageDirection.INBOUND
    mock_record.connection_type = "AS2"
    mock_record.sender_id = "SENDER_X"
    mock_record.receiver_id = "RECEIVER_X"
    mock_record.gs_sender_id = "SENDER_X"
    mock_record.gs_receiver_id = "RECEIVER_X"
    mock_record.format_standard = "X12"
    mock_record.transaction_type = "850"
    mock_record.storage_uri = None
    mock_record.status = MessageStatus.RECEIVED
    mock_record.trading_partner_id = "PARTNER_X"
    mock_record.created_at = datetime.now(UTC)
    mock_record.updated_at = datetime.now(UTC)

    mock_result.scalar_one_or_none.return_value = mock_record
    mock_session.execute.return_value = mock_result

    adapter = make_adapter(mock_session)
    result = await adapter.get_edi_message(str(mock_record.trace_id))

    assert result is not None
    assert result.edi_data == "s3://foo"
    assert result.format_standard == "X12"
    assert result.status == MessageStatus.RECEIVED


async def test_update_edi_message_status() -> None:
    mock_session = AsyncMock()
    adapter = make_adapter(mock_session)

    trace_id = str(uuid.uuid4())
    await adapter.update_edi_message_status(trace_id, MessageStatus.TRANSFORMED)

    mock_session.execute.assert_awaited_once()


async def test_save_api_payload() -> None:
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result
    adapter = make_adapter(mock_session)

    trace_id = str(uuid.uuid4())
    await adapter.save_api_payload(
        trace_id, MessageDirection.OUTBOUND, {"data": "foo"}, MessageStatus.PENDING_DELIVERY
    )

    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, ApiGateway)
    assert str(added_obj.trace_id) == trace_id
    assert added_obj.payload == {"data": "foo"}

    mock_session.flush.assert_awaited_once()


async def test_publish_outbox_event() -> None:
    mock_session = AsyncMock()
    adapter = make_adapter(mock_session)

    idempotency_key = str(uuid.uuid4())
    await adapter.publish_outbox_event(idempotency_key, "DELIVER", {"trace_id": "123"})

    mock_session.execute.assert_awaited_once()
    mock_session.flush.assert_awaited_once()


async def test_get_api_payload() -> None:
    mock_session = AsyncMock()
    mock_result = MagicMock()

    mock_record = MagicMock(spec=ApiGateway)
    mock_record.trace_id = uuid.uuid4()
    mock_record.storage_uri = "s3://out"
    mock_record.status = MessageStatus.PENDING_DELIVERY

    # fake storage needs the uri
    adapter = make_adapter(mock_session)
    adapter.storage.store["s3://out"] = b'{"data": "foo"}'

    mock_result.scalar_one_or_none.return_value = mock_record
    mock_session.execute.return_value = mock_result

    result = await adapter.get_api_payload(str(mock_record.trace_id))

    assert result is not None
    assert result["status"] == MessageStatus.PENDING_DELIVERY
    assert result["payload"] == {"data": "foo"}


async def test_update_api_payload_status() -> None:
    mock_session = AsyncMock()
    adapter = make_adapter(mock_session)

    trace_id = str(uuid.uuid4())
    await adapter.update_api_payload_status(trace_id, MessageStatus.DELIVERED)

    mock_session.execute.assert_awaited_once()
    mock_session.flush.assert_awaited_once()


async def test_get_as2_partner_inactive_raises() -> None:
    from edi.adapters.outbound.database.models.data_plane import AS2Partner, AS2Partnership

    mock_session = AsyncMock()

    mock_partner = MagicMock(spec=AS2Partner)
    mock_partner.active = False

    mock_partnership = MagicMock(spec=AS2Partnership)
    mock_partnership.active = True

    mock_result = MagicMock()
    mock_result.first.return_value = (mock_partner, mock_partnership)
    mock_session.execute.return_value = mock_result

    adapter = make_adapter(mock_session)

    with pytest.raises(ValueError, match="exists but is inactive"):
        await adapter.get_as2_partner("as2_123")


async def test_get_as2_partnership_inactive_raises() -> None:
    from edi.adapters.outbound.database.models.data_plane import AS2Partner, AS2Partnership

    mock_session = AsyncMock()

    mock_partner = MagicMock(spec=AS2Partner)
    mock_partner.active = True

    mock_partnership = MagicMock(spec=AS2Partnership)
    mock_partnership.active = False

    mock_result = MagicMock()
    mock_result.first.return_value = (mock_partner, mock_partnership)
    mock_session.execute.return_value = mock_result

    adapter = make_adapter(mock_session)

    with pytest.raises(ValueError, match="Partnership for as2_123 exists but is inactive"):
        await adapter.get_as2_partner("as2_123")


async def test_get_local_as2_partner_inactive_raises() -> None:
    from edi.adapters.outbound.database.models.data_plane import AS2Partner

    mock_session = AsyncMock()

    mock_partner = MagicMock(spec=AS2Partner)
    mock_partner.active = False

    mock_result = MagicMock()
    mock_result.scalars().first.return_value = mock_partner
    mock_session.execute.return_value = mock_result

    adapter = make_adapter(mock_session)

    with pytest.raises(ValueError, match="Local AS2 Partner as2_123 exists but is inactive"):
        await adapter.get_local_as2_partner("as2_123")
