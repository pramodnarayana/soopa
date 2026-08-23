from unittest.mock import AsyncMock

import pytest

from edi.application.use_cases.api_receiver_service import ApiReceiverService


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

    mock_uow.transactions.create_edi_json.assert_awaited_once()
    _create_args, create_kwargs = mock_uow.transactions.create_edi_json.await_args
    assert create_kwargs["payload"]["transaction_type"] == "850"

    mock_uow.data_plane_outbox.publish_outbox_event.assert_awaited_once()

    _args, kwargs = mock_uow.data_plane_outbox.publish_outbox_event.call_args
    from edi.domain.events import PipelineEventType

    assert kwargs["event_type"] == PipelineEventType.TRANSFORM_EVENT
    assert kwargs["idempotency_key"] == trace_id


@pytest.mark.asyncio
async def test_process_api_edi_json_heading():
    mock_uow = AsyncMock()
    svc = ApiReceiverService(mock_uow)
    trace_id = await svc.process_api_edi_json(
        tenant_id=1,
        trading_partner_id="PARTNER_X",
        payload=[
            {"heading": {"transaction_set_header_ST": {"transaction_set_identifier_code": "850"}}}
        ],
    )
    assert trace_id is not None
    mock_uow.transactions.create_edi_json.assert_awaited_once()
    _create_args, create_kwargs = mock_uow.transactions.create_edi_json.await_args
    assert create_kwargs["payload"]["transaction_type"] == "850"


@pytest.mark.asyncio
async def test_process_api_edi_json_st_segment():
    mock_uow = AsyncMock()
    svc = ApiReceiverService(mock_uow)
    trace_id = await svc.process_api_edi_json(
        tenant_id=1, trading_partner_id="PARTNER_X", payload=[{"ST": {"ST01": "855"}}]
    )
    assert trace_id is not None
    mock_uow.transactions.create_edi_json.assert_awaited_once()
    _create_args, create_kwargs = mock_uow.transactions.create_edi_json.await_args
    assert create_kwargs["payload"]["transaction_type"] == "855"


@pytest.mark.asyncio
async def test_process_api_edi_json_list_extraction():
    mock_uow = AsyncMock()
    svc = ApiReceiverService(mock_uow)
    payload = [
        {"ST": {"ST01": "850"}, "BEG": {"BEG03": "123"}, "foo": "bar"},
        {"ST": {"ST01": "850"}, "BEG": {"BEG03": "456"}, "foo": "baz"},
    ]
    trace_id = await svc.process_api_edi_json(
        tenant_id=1, trading_partner_id="PARTNER_X", payload=payload
    )
    assert trace_id is not None
    mock_uow.transactions.create_edi_json.assert_awaited_once()
    _create_args, create_kwargs = mock_uow.transactions.create_edi_json.await_args

    # Assert business_metadata aggregation for lists
    assert create_kwargs["payload"]["business_metadata"] == {
        "po_number": ["123", "456"],
        "business_reference": ["123", "456"],
        "_routing": {"trading_partner_id": "PARTNER_X"},
    }
