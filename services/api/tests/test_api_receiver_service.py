from unittest.mock import AsyncMock

import pytest
from api.services.api_receiver_service import ApiReceiverService


@pytest.mark.asyncio
async def test_process_api_edi_json_success():
    mock_uow = AsyncMock()

    svc = ApiReceiverService(mock_uow)
    trace_id = await svc.process_api_edi_json(
        tenant_id=1,
        trading_partner_id="PARTNER_X",
        payload={"transaction_type": "850", "payload": "data"},
    )

    assert trace_id is not None
    mock_uow.data_plane.create_edi_json.assert_awaited_once()
    mock_uow.data_plane.publish_outbox_event.assert_awaited_once()

    args, kwargs = mock_uow.data_plane.publish_outbox_event.call_args
    from domain.events import PipelineEventType

    assert kwargs["event_type"] == PipelineEventType.TRANSFORM_EVENT
