import typing

from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

"""
Unit tests for the PipelineLifecycleUseCase.
Uses Fake Data Plane Unit Of Work.
"""

import pytest

from edi.application.use_cases.pipeline.pipeline_lifecycle_use_case import PipelineLifecycleUseCase
from edi.domain.enums import EdiDirection as MessageDirection
from edi.domain.enums import MessageStatus, PipelineEventType
from edi.testing.fakes.pipeline_fakes import FakeDataPlaneUnitOfWork

pytestmark = pytest.mark.asyncio


def make_use_case(uow: FakeDataPlaneUnitOfWork | None = None) -> PipelineLifecycleUseCase:
    u = uow or FakeDataPlaneUnitOfWork()

    uow_casted = typing.cast(DataPlaneUnitOfWorkPort, u)
    return PipelineLifecycleUseCase(uow=uow_casted)


async def test_handle_transform_completed_inbound() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-inbound"

    # Seed data
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "status": MessageStatus.PROCESSING,
    }

    payload = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "gs_sender_id": "GS_SENDER",
        "gs_receiver_id": "GS_RECEIVER",
        "transaction_type": "850",
    }

    use_case = make_use_case(uow=uow)
    await use_case.handle_transform_completed(payload)

    # Assertions
    saved_edi = uow.repository.edi_messages.get(trace_id)
    assert saved_edi is not None
    assert saved_edi["status"] == MessageStatus.TRANSFORMED
    assert saved_edi["gs_sender_id"] == "GS_SENDER"
    assert saved_edi["gs_receiver_id"] == "GS_RECEIVER"
    assert saved_edi["transaction_type"] == "850"

    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == PipelineEventType.DELIVER_EVENT
    assert event["payload"]["trace_id"] == trace_id


async def test_handle_transform_completed_outbound() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-outbound"

    # Seed data
    uow.repository.edi_json[trace_id] = {
        "trace_id": trace_id,
        "status": MessageStatus.PROCESSING,
    }

    payload = {
        "trace_id": trace_id,
        "direction": MessageDirection.OUTBOUND,
        "trading_partner_id": "tp1",
        "standard": "X12",
        "isa_sender_id": "ISA_SENDER",
        "isa_receiver_id": "ISA_RECEIVER",
        "gs_sender_id": "GS_SENDER",
        "gs_receiver_id": "GS_RECEIVER",
    }

    use_case = make_use_case(uow=uow)
    await use_case.handle_transform_completed(payload)

    # Assertions
    saved_json = uow.repository.edi_json.get(trace_id)
    assert saved_json is not None
    assert saved_json["status"] == MessageStatus.TRANSFORMED
    assert saved_json["trading_partner_id"] == "tp1"
    assert saved_json["standard"] == "X12"
    assert saved_json["sender_id"] == "ISA_SENDER"
    assert saved_json["receiver_id"] == "ISA_RECEIVER"
    assert saved_json["gs_sender_id"] == "GS_SENDER"
    assert saved_json["gs_receiver_id"] == "GS_RECEIVER"

    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == PipelineEventType.DELIVER_EVENT
    assert event["payload"]["trace_id"] == trace_id


async def test_handle_delivery_completed_inbound() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-inbound-dlv"

    uow.repository.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "status": MessageStatus.PENDING_DELIVERY,
    }

    payload = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "status": MessageStatus.DELIVERED,
    }

    use_case = make_use_case(uow=uow)
    await use_case.handle_delivery_completed(payload)

    saved_api = uow.repository.api_gateway.get(trace_id)
    assert saved_api is not None
    assert saved_api["status"] == str(MessageStatus.DELIVERED)


async def test_handle_delivery_completed_null_direction_defaults_to_inbound() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-null-direction-dlv"
    uow.repository.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "status": MessageStatus.PENDING_DELIVERY,
    }

    await make_use_case(uow=uow).handle_delivery_completed(
        {
            "trace_id": trace_id,
            "direction": None,
            "status": MessageStatus.DELIVERED,
        }
    )

    assert uow.repository.api_gateway[trace_id]["status"] == str(MessageStatus.DELIVERED)


async def test_handle_delivery_completed_outbound() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-outbound-dlv"

    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "status": MessageStatus.PENDING_DELIVERY,
    }

    payload = {
        "trace_id": trace_id,
        "direction": MessageDirection.OUTBOUND,
        "status": MessageStatus.DELIVERED,
    }

    use_case = make_use_case(uow=uow)
    await use_case.handle_delivery_completed(payload)

    saved_edi = uow.repository.edi_messages.get(trace_id)
    assert saved_edi is not None
    assert saved_edi["status"] == str(MessageStatus.DELIVERED)
