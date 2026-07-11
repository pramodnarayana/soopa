from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from api.services.outbound_service import OutboundService


@pytest.mark.asyncio
async def test_process_outbound_message_route_not_found():
    mock_uow = AsyncMock()
    mock_uow.control_plane.get_outbound_route_by_trading_partner_id.return_value = None

    svc = OutboundService(mock_uow)
    with pytest.raises(ValueError, match="not found or not active"):
        await svc.process_outbound_message(1, "PARTNER_X", {})


@pytest.mark.asyncio
async def test_process_outbound_message_success():
    mock_uow = AsyncMock()
    mock_route = MagicMock(
        id=uuid4(),
        default_standard="x12",
        as2_partner_id=uuid4(),
        sftp_partner_id=None,
        isa_sender_id="S",
        isa_receiver_id="R",
    )
    mock_uow.control_plane.get_outbound_route_by_trading_partner_id.return_value = mock_route

    svc = OutboundService(mock_uow)
    trace_id = await svc.process_outbound_message(1, "PARTNER_X", {"transaction_type": "850"})

    assert trace_id is not None
    mock_uow.data_plane.create_edi_json.assert_awaited_once()
    mock_uow.data_plane.create_api_gateway.assert_awaited_once()
    mock_uow.data_plane.create_outbox_event.assert_awaited_once()
