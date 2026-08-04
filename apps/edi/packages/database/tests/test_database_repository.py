import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.control_plane import AS2Partner, InboundRoute
from database.repository import (
    EdiMessageRepository,
    TradingPartnerRepository,
)

pytestmark = pytest.mark.asyncio


async def test_trading_partner_repository_find_by_as2_id() -> None:
    mock_session = AsyncMock()
    tenant_id = 1

    partner = AS2Partner(
        tenant_id=tenant_id,
        as2_id="test_partner",
        active=True,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = partner
    mock_session.execute.return_value = mock_result

    repo = TradingPartnerRepository(mock_session)
    result = await repo.find_by_as2_id(tenant_id, "test_partner")

    assert result == partner
    mock_session.execute.assert_called_once()


async def test_edi_message_repository_save_message() -> None:
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    tenant_id = 1

    repo = EdiMessageRepository(mock_session)

    trace_id = uuid.uuid4()
    result = await repo.save_message(
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction="INBOUND",
        connection_type="AS2",
        edi_data="s3://bucket/tenants/1/inbound/test.edi",
        sender_id="SENDER123",
        receiver_id="RECV456",
        status="RECEIVED",
        message_id="msg-123",
    )

    assert result.direction == "INBOUND"
    assert result.status == "RECEIVED"
    assert result.sender_id == "SENDER123"
    assert result.receiver_id == "RECV456"
    assert result.edi_data == "s3://bucket/tenants/1/inbound/test.edi"
    assert result.message_id == "msg-123"
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()


async def test_inbound_route_repository_get_inbound_route() -> None:
    from database.repository import InboundRouteRepository

    mock_session = AsyncMock()
    mock_result = MagicMock()

    route = InboundRoute(
        id=uuid.uuid4(),
        tenant_id=1,
        isa_sender_id="SENDER",
        isa_receiver_id="RECEIVER",
        transaction_type="850",
        active=True,
    )
    mock_result.scalar_one_or_none.return_value = route
    mock_session.execute.return_value = mock_result

    repo = InboundRouteRepository(mock_session)
    result = await repo.get_inbound_route("SENDER", "RECEIVER", tenant_id=1, transaction_type="850")

    assert result == route
    mock_session.execute.assert_called_once()


async def test_inbound_route_repository_get_inbound_route_no_match() -> None:
    from database.repository import InboundRouteRepository

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    repo = InboundRouteRepository(mock_session)
    result = await repo.get_inbound_route("SENDER", "RECEIVER", tenant_id=1, transaction_type="850")

    assert result is None
    mock_session.execute.assert_called_once()


async def test_inbound_route_repository_get_inbound_route_no_transaction_type() -> None:
    from database.repository import InboundRouteRepository

    mock_session = AsyncMock()
    mock_result = MagicMock()
    route = InboundRoute(
        id=uuid.uuid4(),
        tenant_id=1,
        isa_sender_id="SENDER",
        isa_receiver_id="RECEIVER",
        transaction_type=None,
        active=True,
    )
    mock_result.scalar_one_or_none.return_value = route
    mock_session.execute.return_value = mock_result

    repo = InboundRouteRepository(mock_session)
    result = await repo.get_inbound_route("SENDER", "RECEIVER", tenant_id=1, transaction_type=None)

    assert result == route
    mock_session.execute.assert_called_once()
